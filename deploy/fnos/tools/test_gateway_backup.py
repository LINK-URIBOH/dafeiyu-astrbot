import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import backup_snapshot


class BackupTests(unittest.TestCase):
    def test_wal_commits_and_encrypted_files_survive_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'backups').mkdir();(root/'astrbot/data').mkdir(parents=True)
            (root/'snowluma/data').mkdir(parents=True)
            (root/'gateway.json').write_text(json.dumps({'backend':'snowluma'}))
            (root/'.env').write_text('COMPOSE_FILE=compose.yaml:compose.snowluma.yaml\n')
            db=root/'astrbot/data/test.sqlite3';con=sqlite3.connect(db)
            con.execute('PRAGMA journal_mode=WAL');con.execute('CREATE TABLE sample(value TEXT)');con.execute("INSERT INTO sample VALUES ('committed-in-wal')");con.commit()
            encrypted=root/'snowluma/data/encrypted.db';encrypted.write_bytes(b'ENCRYPTED-database')
            encrypted.with_name('encrypted.db-wal').write_bytes(b'opaque-wal')
            calls=[];real=subprocess.run
            def invoke(args,**kw):
                calls.append(args)
                if args[0]=='docker':return SimpleNamespace(returncode=0,stdout='true\n')
                return real(args,**kw)
            archive=root/'backups/result.tar.gz'
            with patch.object(backup_snapshot,'BASE',root),patch.object(backup_snapshot.subprocess,'run',side_effect=invoke):
                backup_snapshot.snapshot(archive)
            with tempfile.TemporaryDirectory() as out,tarfile.open(archive) as tar:
                tar.extractall(out,filter='data')
                with sqlite3.connect(Path(out)/'astrbot/data/test.sqlite3') as restored:
                    self.assertEqual(restored.execute('SELECT value FROM sample').fetchone()[0],'committed-in-wal')
                    self.assertEqual(restored.execute('PRAGMA quick_check').fetchone()[0],'ok')
                self.assertEqual((Path(out)/'snowluma/data/encrypted.db-wal').read_bytes(),b'opaque-wal')
                self.assertTrue((Path(out)/'.env').is_file())
            self.assertIn(['docker','unpause','dafeiyu-snowluma'],calls)
            self.assertFalse(list((root/'backups').glob('.snapshot-*')))
            con.close()

    def test_copy_failure_always_unpauses_gateway(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'backups').mkdir();(root/'astrbot/data').mkdir(parents=True)
            calls=[]
            def invoke(args,**kw):
                calls.append(args)
                if args[0]=='cp':raise subprocess.CalledProcessError(1,args)
                return SimpleNamespace(returncode=0,stdout='true\n')
            with patch.object(backup_snapshot,'BASE',root),patch.object(backup_snapshot.subprocess,'run',side_effect=invoke):
                with self.assertRaises(subprocess.CalledProcessError):backup_snapshot.snapshot(root/'backups/result.tar.gz')
            self.assertIn(['docker','unpause','dafeiyu-napcat'],calls)
            self.assertFalse((root/'backups/result.tar.gz').exists())


if __name__=='__main__':unittest.main()
