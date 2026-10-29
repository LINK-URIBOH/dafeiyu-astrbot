import base64
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from test_snowluma_video import plugin, mod
from unittest.mock import patch


class GatewayMediaTests(unittest.IsolatedAsyncioTestCase):
    def voice_event(self,text='用语音回复测试成功'):
        extra={}
        return SimpleNamespace(message_str=text,unified_msg_origin='qq:FriendMessage:test',
            get_extra=extra.get,set_extra=extra.__setitem__,send=AsyncMock(),chain_result=lambda x:x)

    async def test_explicit_tts_calls_native_provider_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as d:
            audio=Path(d)/'test.mp3';audio.write_bytes(b'ID3audio')
            p=plugin();provider=SimpleNamespace(get_audio=AsyncMock(return_value=str(audio)))
            p.context=SimpleNamespace(get_using_tts_provider_async=AsyncMock(return_value=provider))
            e=self.voice_event()
            with patch.object(mod.Record,'fromFileSystem',create=True,side_effect=lambda path,**kw:('record',path)):
                result=[x async for x in p.native_speak(e,'测试成功')]
                again=[x async for x in p.native_speak(e,'测试成功')]
            self.assertIn('提交平台发送',result[0]);self.assertIn('不重复',again[0])
            provider.get_audio.assert_awaited_once_with('测试成功');e.send.assert_awaited_once()

    async def test_tts_requires_explicit_request_and_limited_text(self):
        p=plugin();p.context=SimpleNamespace(get_using_tts_provider_async=AsyncMock())
        for text,content in [('你好','你好'),('不要语音回复','你好'),('用语音回复','x'*301)]:
            result=[x async for x in p.native_speak(self.voice_event(text),content)]
            self.assertIn('未发送语音',result[0])
        p.context.get_using_tts_provider_async.assert_not_awaited()

    async def test_tts_provider_failure_does_not_claim_delivery(self):
        p=plugin();p.context=SimpleNamespace(get_using_tts_provider_async=AsyncMock(side_effect=RuntimeError('test')))
        e=self.voice_event();result=[x async for x in p.native_speak(e,'测试')]
        self.assertIn('未发送语音',result[0]);e.send.assert_not_awaited()

    async def test_tts_hint_only_in_explicit_turn(self):
        p=plugin();req=SimpleNamespace(system_prompt='existing')
        await p.explicit_voice_hint(self.voice_event('你好'),req);self.assertEqual(req.system_prompt,'existing')
        await p.explicit_voice_hint(self.voice_event(),req);self.assertIn('tts_speak',req.system_prompt)

    async def transcribe(self,data):
        p=plugin();p._asr_file=AsyncMock(return_value='ok')
        event=SimpleNamespace(bot=SimpleNamespace(get_record=AsyncMock(return_value=data)))
        result=await p._transcribe_voice(event,SimpleNamespace(file='voice-id'))
        return result,p

    async def test_converted_base64_preferred_over_original_silk_url(self):
        payload=b'ID3'+b'\x00'*100
        result,p=await self.transcribe({'file':'https://invalid.example/silk','out_format':'mp3','base64':base64.b64encode(payload).decode()})
        self.assertEqual(result,'ok');self.assertEqual(p._asr_file.await_count,1)
        self.assertFalse(Path(p._asr_file.call_args.args[0]).exists())

    async def test_nested_response(self):
        result,_=await self.transcribe({'data':{'out_format':'mp3','base64':base64.b64encode(b'\xff\xfb'+b'\0'*10).decode()}})
        self.assertEqual(result,'ok')

    async def test_invalid_or_unconverted_payload_never_reaches_asr(self):
        for data in [
            {'out_format':'mp3','base64':'invalid@'},
            {'out_format':'mp3','base64':''},
            {'out_format':'wav','base64':base64.b64encode(b'ID3data').decode()},
            {'out_format':'mp3','base64':base64.b64encode(b'\x02#!SILK_V3').decode()},
            {'out_format':'mp3','base64':'A'*9_333_337}]:
            with self.subTest(data_keys=list(data)):
                result,p=await self.transcribe(data)
                self.assertIsNone(result);p._asr_file.assert_not_awaited()

    async def test_napcat_local_mp3_compatibility(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'voice.mp3';f.write_bytes(b'ID3voice')
            result,p=await self.transcribe({'file':str(f)})
            self.assertEqual(result,'ok');self.assertTrue(f.exists())

    async def test_silk_file_not_mislabelled_mp3(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'voice.mp3';f.write_bytes(b'\x02#!SILK_V3data')
            result,p=await self.transcribe({'file':str(f)})
            self.assertIsNone(result);p._asr_file.assert_not_awaited()

    async def test_refresh_video_through_original_message(self):
        p=plugin();p._download_ok=AsyncMock(return_value='/tmp/video.mp4')
        bot=SimpleNamespace(get_msg=AsyncMock(return_value={'message':[{'type':'video','data':{'url':'https://media.example/fresh'}}]}),get_file=AsyncMock())
        e=SimpleNamespace(bot=bot,message_obj=SimpleNamespace(message_id='-12'))
        result=await p._resolve_video(e,SimpleNamespace(file='video-id'),'/tmp')
        self.assertEqual(result,'/tmp/video.mp4');bot.get_msg.assert_awaited_once_with(message_id='-12');bot.get_file.assert_not_awaited()


if __name__=='__main__':unittest.main()
