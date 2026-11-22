import contextlib,io,json,sys,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import apply_source_update as update

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/'live';self.base.mkdir()
        self.source=Path(__file__).resolve().parents[3]
        fnos=self.source/'deploy/fnos'
        for name in ('compose.yaml','versions.lock.json'):
            (self.base/name).write_bytes((fnos/name).read_bytes())
        (self.base/'astrbot/data').mkdir(parents=True)
        self.user=self.base/'astrbot/data/cmd_config.json';self.user.write_text('USER_SETTINGS_UNCHANGED')
        (self.base/'patches').mkdir()
        import shutil
        for name in ('dafeiyu_group_context.py','group_chat_context.py','proactive_context_service.py','sitecustomize.py','omnidraw_custom_endpoint_impl.py'):
            shutil.copy2(fnos/'patches'/name,self.base/'patches'/name)
        (self.base/'patches/stage.py').write_text('old-stage')
        (self.base/'incoming').mkdir()
        self.backup=self.base/'backup.tar.gz';self.backup.write_bytes(b'validated-by-caller')
    def run_update(self,apply=False,running=False):
        args=['apply','--source',str(self.source),'--base',str(self.base),'--backup',str(self.backup)]
        if apply:args.append('--apply')
        with patch.object(sys,'argv',args),patch.object(update.subprocess,'run') as validate,patch.object(update.subprocess,'check_output',return_value=json.dumps([{'State':{'Running':running}}]).encode()),contextlib.redirect_stdout(io.StringIO()):
            update.main()
            validate.assert_called_once()  # The separate patch verifier is mandatory.
    def test_default_is_read_only(self):
        self.run_update();self.assertEqual((self.base/'patches/stage.py').read_text(),'old-stage')
        self.assertFalse(list((self.base/'incoming').iterdir()))
    def test_running_service_rejected_without_writes(self):
        with self.assertRaisesRegex(AssertionError,'Stop AstrBot'):self.run_update(True,True)
        self.assertEqual((self.base/'patches/stage.py').read_text(),'old-stage')
        self.assertFalse(list((self.base/'incoming').iterdir()))
    def test_apply_keeps_user_data_and_saves_code_rollback(self):
        self.run_update(True)
        self.assertEqual(self.user.read_text(),'USER_SETTINGS_UNCHANGED')
        before=next((self.base/'incoming').iterdir())
        self.assertEqual((before/'patches/stage.py').read_text(),'old-stage')
        self.assertNotIn('astrbot/data/cmd_config.json',json.loads((before/'files.json').read_text()))
        self.assertEqual((self.base/'patches/stage.py').read_bytes(),(self.source/'deploy/fnos/patches/stage.py').read_bytes())
        lock=json.loads((self.base/'patches.lock.json').read_text())
        import hashlib
        self.assertEqual(lock['files']['patches/dafeiyu_group_context.py'],hashlib.sha256((self.base/'patches/dafeiyu_group_context.py').read_bytes()).hexdigest())
    def test_partial_write_failure_restores_originals(self):
        replace=update.os.replace;calls=0
        def fail_second(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('synthetic write failure')
            return replace(*args)
        with patch.object(update.os,'replace',side_effect=fail_second):
            with self.assertRaisesRegex(OSError,'synthetic'):self.run_update(True)
        self.assertEqual((self.base/'patches/stage.py').read_text(),'old-stage')
        self.assertEqual(self.user.read_text(),'USER_SETTINGS_UNCHANGED')
        self.assertFalse((self.base/'patches/face_convert_main.py').exists())

if __name__=='__main__':unittest.main()
