"""Exercise the actual pinned core stages, using synthetic events and TTS only."""
import copy,importlib.util,inspect,sys,tempfile,wave
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.message.message_event_result import MessageEventResult,ResultContentType
from astrbot.core.message.components import Plain,Record

PATCHES=Path(__file__).resolve().parents[1]/'patches'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
load('astrbot.core.pipeline.chat_layout',PATCHES/'chat_layout.py')
decorate=load('astrbot.core.pipeline.result_decorate.fnos_candidate',PATCHES/'stage.py')
respond=load('astrbot.core.pipeline.respond.fnos_candidate',PATCHES/'respond_stage.py')

class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.audio=Path(self.folder.name)/'voice.wav'
        with wave.open(str(self.audio),'w') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*32000)
        self.provider=SimpleNamespace(get_audio=AsyncMock(return_value=str(self.audio)))
        cfg=copy.deepcopy(DEFAULT_CONFIG);cfg['content_safety']['also_use_in_response']=False;cfg['t2i']=False
        cfg['platform_settings'].update(reply_prefix='',reply_with_mention=False,reply_with_quote=False,forward_threshold=10000)
        cfg['platform_settings']['segmented_reply'].update(enable=True,only_llm_result=True,words_count_threshold=1000,regex=r'.*?[。？！]+|.+$',content_cleanup_rule='',interval_method='random',interval='0,0')
        cfg['provider_tts_settings'].update(enable=True,trigger_probability=1,dual_output=True,use_file_service=False)
        self.ctx=SimpleNamespace(astrbot_config=cfg,plugin_manager=SimpleNamespace(context=SimpleNamespace(get_using_tts_provider_async=AsyncMock(return_value=self.provider))))
        self.stage=decorate.ResultDecorateStage();await self.stage.initialize(self.ctx)
        self.response=respond.RespondStage();await self.response.initialize(self.ctx)
        self.hooks=patch.object(decorate.star_handlers_registry,'get_handlers_by_event_type',return_value=[]);self.hooks.start();self.addCleanup(self.hooks.stop)
        self.after=patch.object(respond,'call_event_hook',AsyncMock(return_value=False));self.after.start();self.addCleanup(self.after.stop)
        self.tts=patch.object(decorate.SessionServiceManager,'should_process_tts_request',AsyncMock(return_value=True));self.tts.start();self.addCleanup(self.tts.stop)
    def event(self,text,**extra):
        result=MessageEventResult().message(text);result.result_content_type=ResultContentType.LLM_RESULT
        e=SimpleNamespace(get_result=lambda:result,plugins_name=set(),unified_msg_origin='qq:FriendMessage:test',get_extra=extra.get,set_extra=extra.__setitem__,get_platform_name=lambda:'aiocqhttp',get_platform_id=lambda:'qq',get_message_type=lambda:None,get_sender_name=lambda:'synthetic',get_sender_id=lambda:'synthetic',_outline_chain=lambda _:'synthetic',is_stopped=lambda:False,send=AsyncMock(),clear_result=Mock())
        return e,result
    async def process(self,stage,event):
        result=stage.process(event)
        if inspect.isasyncgen(result):
            async for _ in result:pass
        else:await result
    async def test_complete_reply_synthesized_once_and_delivered_with_balanced_title(self):
        e,result=self.event('请看《是真的吗？下一句》这个标题。再聊一句。')
        await self.process(self.stage,e)
        self.provider.get_audio.assert_awaited_once()
        self.assertEqual(sum(isinstance(c,Record) for c in result.chain),1)
        await self.process(self.response,e)
        texts=[''.join(c.text for c in a.args[0].chain if isinstance(c,Plain)) for a in e.send.await_args_list]
        self.assertTrue(any('《是真的吗？下一句》' in s for s in texts))
        self.assertEqual(sum(any(isinstance(c,Record) for c in a.args[0].chain) for a in e.send.await_args_list),1)
    async def test_native_tool_already_sent_prevents_second_tts_charge(self):
        e,_=self.event('已经收到。',dafeiyu_native_tts_sent=True)
        await self.process(self.stage,e);self.provider.get_audio.assert_not_awaited()
    async def test_tts_error_falls_back_to_text(self):
        self.provider.get_audio.side_effect=RuntimeError('synthetic')
        e,result=self.event('失败时保留文字。');await self.process(self.stage,e)
        self.assertFalse(any(isinstance(c,Record) for c in result.chain))
        await self.process(self.response,e);self.assertTrue(e.send.await_count)
    async def test_stopped_reply_sends_nothing(self):
        e,_=self.event('已被打断。');e.is_stopped=lambda:True
        await self.process(self.response,e);e.send.assert_not_awaited();e.clear_result.assert_called_once()

if __name__=='__main__':unittest.main()
