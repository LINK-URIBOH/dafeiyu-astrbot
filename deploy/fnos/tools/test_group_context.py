"""Integration/regression checks using a disposable SQLite database and synthetic messages."""
import asyncio
from datetime import datetime
import importlib.util
import json
import os
os.environ['DAFEIYU_GROUP_ID'] = '123456789'  # synthetic test group only
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

PATCHES = Path(__file__).resolve().parents[1] / 'patches'
if not PATCHES.exists():
    PATCHES = Path('/tmp/group-tests/patches')
sys.path.insert(0, str(PATCHES))
import dafeiyu_group_context as policy
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.platform_message_history_mgr import PlatformMessageHistoryManager
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain, Image
from astrbot.api.platform import MessageType

spec = importlib.util.spec_from_file_location('group_context_under_test', PATCHES / 'group_chat_context.py')
group_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(group_module)

def cfg():
    return {'provider_ltm_settings': {'group_icl_enable': True, 'group_message_max_cnt': 50,
        'image_caption': True, 'image_caption_provider_id': 'bailian_vision',
        'active_reply': {'enable': True, 'method': 'possibility_reply', 'possibility_reply': 0.1, 'whitelist': [policy.TARGET_UMO]}},
        'provider_settings': {'image_caption_prompt': 'synthetic test'}}

class Event:
    def __init__(self, text, sender='member-A', umo=policy.TARGET_UMO, image=False):
        self.unified_msg_origin = umo
        self.message_str = text
        self.is_at_or_wake_command = False
        self.extras = {}
        self.message_obj = SimpleNamespace(sender=SimpleNamespace(nickname=sender), message=[Plain(text)])
        if image:
            self.message_obj.message.append(Image(file='synthetic-image.png', url='https://example.com/synthetic.png'))
    def get_extra(self, key, default=None): return self.extras.get(key, default)
    def set_extra(self, key, value): self.extras[key] = value
    def get_messages(self): return self.message_obj.message
    def get_message_type(self): return MessageType.GROUP_MESSAGE
    def get_group_id(self): return self.unified_msg_origin.split(':')[-1]
    def get_platform_id(self): return 'qq'
    def get_self_id(self): return 'robot'
    def get_sender_id(self): return self.message_obj.sender.nickname

async def context_for(path):
    db = SQLiteDatabase(str(path))
    await db.initialize()
    manager = PlatformMessageHistoryManager(db)
    ctx = SimpleNamespace(get_db=lambda: db, message_history_manager=manager, get_config=lambda **_: cfg())
    return db, ctx, group_module.GroupChatContext(None, ctx)

async def add(ctx, group, text, sender='member-A', image=False, capture=True, umo=policy.TARGET_UMO):
    event = Event(text, sender, umo, image)
    row = await ctx.message_history_manager.insert_message_chain('qq', umo,
        MessageChain(chain=event.get_messages()), role='user', sender_id=sender, sender_name=sender, max_messages=700)
    event.set_extra('_current_platform_message_history_id', row.id)
    if capture:
        await group.handle_message(event)
    return event

def request(): return SimpleNamespace(contexts=[], extra_user_content_parts=[])
def background(req): return '\n'.join(getattr(p, 'text', '') for p in req.extra_user_content_parts)

async def probe(path, current_id):
    db, ctx, group = await context_for(path)
    group.get_image_caption = AsyncMock(side_effect=AssertionError('Old image must not be re-captioned'))
    event = Event('probe');event.set_extra('_current_platform_message_history_id', current_id)
    req=request();await group.on_req_llm(event,req)
    text=background(req)
    result={'text_survives': 'TEXT_NONCE_A' in text, 'image_caption_survives': 'IMAGE_NONCE_BLUE' in text,
            'current_excluded': 'CURRENT_NONCE_B' not in text, 'caption_calls': group.get_image_caption.await_count}
    await db.engine.dispose()
    return result

class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'context.db'
        self.db, self.ctx, self.group = await context_for(self.path)
        self.group.get_image_caption = AsyncMock(return_value='IMAGE_NONCE_BLUE 蓝色鲸鱼')
    async def asyncTearDown(self):
        await self.db.engine.dispose()
        self.temp.cleanup()

    async def test_member_shared_context_and_fresh_process_restore(self):
        first = await add(self.ctx,self.group,'TEXT_NONCE_A',image=True)
        # Retry of the same event must not call vision twice.
        await self.group.handle_message(first)
        self.assertEqual(self.group.get_image_caption.await_count,1)
        current = await add(self.ctx,self.group,'CURRENT_NONCE_B',sender='member-B')
        req=request();await self.group.on_req_llm(current,req)
        self.assertIn('member-A',background(req));self.assertIn('TEXT_NONCE_A',background(req))
        self.assertIn('IMAGE_NONCE_BLUE',background(req));self.assertNotIn('CURRENT_NONCE_B',background(req))
        audit=json.loads((self.path.parent/'group-context-live.json').read_text())
        self.assertEqual(audit['injected_message_ids'],[first.get_extra('_current_platform_message_history_id')])
        self.assertNotIn('TEXT_NONCE_A',json.dumps(audit))
        await self.db.engine.dispose()
        result = subprocess.run([sys.executable,__file__,'--probe',str(self.path),str(current.get_extra('_current_platform_message_history_id'))],capture_output=True,text=True,check=True)
        value=json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(value['text_survives']);self.assertTrue(value['image_caption_survives'])
        self.assertTrue(value['current_excluded']);self.assertEqual(value['caption_calls'],0)

    async def test_reset_boundary_persists_and_history_remains_queryable(self):
        await add(self.ctx,self.group,'BEFORE_RESET_NONCE')
        command = await add(self.ctx,self.group,'/reset',capture=False)
        await self.group.remove_session(command)
        self.group=group_module.GroupChatContext(None,self.ctx)
        current=await add(self.ctx,self.group,'AFTER_RESET_CURRENT',sender='member-B')
        req=request();await self.group.on_req_llm(current,req)
        self.assertNotIn('BEFORE_RESET_NONCE',background(req))
        rows=await self.ctx.message_history_manager.get('qq',policy.TARGET_UMO)
        self.assertGreaterEqual(len(rows),3)
        proactive=await policy.load_proactive_records(self.ctx)
        self.assertEqual(len(proactive),1)
        self.assertNotIn('BEFORE_RESET_NONCE',json.dumps(proactive[0].content))

    async def test_commands_scope_order_and_duplicate_injection(self):
        await add(self.ctx,self.group,'FIRST')
        await add(self.ctx,self.group,'/help',capture=False)
        await add(self.ctx,self.group,'OTHER_GROUP_SECRET',umo='qq:GroupMessage:222')
        current=await add(self.ctx,self.group,'CURRENT')
        req=request();req.contexts=[{'role':'user','content':'question '+policy.OPEN+'OLD_SNAPSHOT'+policy.CLOSE}]
        await self.group.on_req_llm(current,req);await self.group.on_req_llm(current,req)
        self.assertEqual(background(req).count(policy.OPEN),1)
        self.assertNotIn('/help',background(req));self.assertNotIn('OTHER_GROUP_SECRET',background(req))
        self.assertNotIn('OLD_SNAPSHOT',str(req.contexts))
        self.assertIn('question',str(req.contexts))

    async def test_quiet_and_probability_and_explicit_wake(self):
        event=Event('ordinary')
        with patch.object(group_module,'is_quiet',return_value=True),patch.object(group_module.random,'random',return_value=0.0):
            self.assertFalse(await self.group.need_active_reply(event))
        with patch.object(group_module,'is_quiet',return_value=False),patch.object(group_module.random,'random',return_value=0.05):
            self.assertTrue(await self.group.need_active_reply(event))
            event.is_at_or_wake_command=True
            self.assertFalse(await self.group.need_active_reply(event))
            # This method only controls random replies; normal waking remains independent.
        event.is_at_or_wake_command=False
        with patch.object(group_module,'is_quiet',return_value=False),patch.object(group_module.random,'random',return_value=0.11):
            self.assertFalse(await self.group.need_active_reply(event))

    async def test_proactive_uses_captions_and_excludes_commands(self):
        await add(self.ctx,self.group,'IMAGE_TEXT',image=True)
        await add(self.ctx,self.group,'/help',capture=False)
        rows=await policy.load_proactive_records(self.ctx)
        self.assertEqual(len(rows),1)
        self.assertIn('IMAGE_NONCE_BLUE',str(rows[0].content))

    async def test_non_target_context_keeps_original_behavior(self):
        event=await add(self.ctx,self.group,'OTHER_A',umo='qq:GroupMessage:222')
        self.assertEqual(len(self.group.raw_records[event.unified_msg_origin]),1)
        current=await add(self.ctx,self.group,'OTHER_B',umo='qq:GroupMessage:222')
        req=request();await self.group.on_req_llm(current,req)
        self.assertIn('OTHER_A',background(req));self.assertNotIn(policy.OPEN,background(req))

    async def test_patched_proactive_service_obeys_reset_and_requested_limit(self):
        name='data.plugins.astrbot_plugin_proactive_chat.core.services.context_service_group_under_test'
        spec=importlib.util.spec_from_file_location(name,PATCHES/'proactive_context_service.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        service=module.ContextService(SimpleNamespace(context=self.ctx))
        await add(self.ctx,self.group,'BEFORE_RESET')
        reset=await add(self.ctx,self.group,'/reset',capture=False);await self.group.remove_session(reset)
        await add(self.ctx,self.group,'AFTER_ONE');await add(self.ctx,self.group,'AFTER_TWO')
        records,count=await service.load_platform_message_history_records(policy.TARGET_UMO,1)
        self.assertEqual(count,1);self.assertIn('AFTER_TWO',str(records[0].content))
        self.assertNotIn('BEFORE_RESET',str(records[0].content))
        records,count=await service.load_platform_message_history_records(policy.TARGET_UMO,0)
        self.assertEqual((records,count),([],0))

    async def test_cold_chat_real_quiet_gate(self):
        from data.plugins.astrbot_plugin_proactive_chat.core.pipeline import flow_orchestrator
        from data.plugins.astrbot_plugin_proactive_chat.utils import time_utils
        plugin=SimpleNamespace(config_service=SimpleNamespace(get_session_config=lambda _: {'enable':True,'schedule_settings':{'quiet_hours':'23-8'}}),timezone=ZoneInfo('Asia/Shanghai'))
        fake=SimpleNamespace(plugin=plugin)
        for hour,expected in [(22,True),(23,False),(7,False),(8,True)]:
            with patch.object(time_utils,'datetime') as clock:
                clock.now.return_value=datetime(2026,10,27,hour,tzinfo=plugin.timezone)
                allowed,reason=await flow_orchestrator.FlowOrchestrator.is_chat_allowed(fake,policy.TARGET_UMO)
                self.assertEqual(allowed,expected)

class BoundsTests(unittest.TestCase):
    def test_time_boundaries(self):
        zone=ZoneInfo('Asia/Shanghai')
        for hour,minute,expected in [(22,59,False),(23,0,True),(7,59,True),(8,0,False)]:
            self.assertEqual(policy.is_quiet(datetime(2026,10,27,hour,minute,tzinfo=zone)),expected)
    def test_row_limits_dedup_and_current_exclusion(self):
        rows=[SimpleNamespace(id=i,platform_id='qq',user_id=policy.TARGET_UMO,content={policy.RENDER_KEY:f'ROW-{i}'}) for i in range(1,81)]
        selected=policy.select_background(rows+rows,0,80)
        self.assertEqual(len(selected),50);self.assertEqual(selected[0],'ROW-30');self.assertEqual(selected[-1],'ROW-79')
    def test_character_budgets(self):
        rows=[SimpleNamespace(id=i,platform_id='qq',user_id=policy.TARGET_UMO,content={policy.RENDER_KEY:'字'*2000}) for i in range(1,90)]
        selected=policy.select_background(rows,0,None)
        self.assertLessEqual(sum(map(len,selected))+len(selected)-1,12000)
        self.assertTrue(all(len(line)<=1000 for line in selected))

if __name__=='__main__':
    if '--probe' in sys.argv:
        print(json.dumps(asyncio.run(probe(sys.argv[2],int(sys.argv[3])))))
    else:
        unittest.main(verbosity=2)
