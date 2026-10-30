"""Exercise upgrades without customer databases or network access."""
import hashlib
import importlib.util
import io
import pathlib
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upgrader', ROOT/'scripts/upgrade.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def bundle(extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name in sorted(module.FILES):
            archive.writestr('mofis-deploy-0.2.0/'+name, '0.2.0\n' if name == 'VERSION' else 'new file')
        if extra:
            archive.writestr('mofis-deploy-0.2.0/'+extra, 'unsafe')
    data = stream.getvalue()
    return data, hashlib.sha256(data).hexdigest()+'  mofis-deploy-0.2.0.zip\n'

class UpgradeTests(unittest.TestCase):
    def test_archive_checks(self):
        data, sums = bundle()
        self.assertEqual(module.unpack(data,sums)[0], '0.2.0')
        with self.assertRaises(ValueError): module.unpack(data,'0'*64+'  mofis-deploy-0.2.0.zip')
        with self.assertRaises(ValueError): module.unpack(data,sums,'0.3.0')
        for name in ['../escape', 'config/db-password']:
            data,sums = bundle(name)
            with self.assertRaises(ValueError): module.unpack(data,sums)

    def fixture(self, root):
        for name in module.FILES:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('old file')
        (root/'VERSION').write_text('0.1.5\n')
        (root/'manage.sh').write_text('#!/bin/sh\necho previous-services-ready\n')
        (root/'.env').write_text('COMPOSE_PROJECT_NAME=original\nPG_DATA_VOLUME=original_pgdata\nSSH_PORT=2223\nMOFIS_DEPLOY_VERSION=0.1.5\n')
        (root/'config').mkdir()
        (root/'config/db-password').write_text('secret')
        (root/'connection.txt').write_text('private connection')

    def test_success_and_rollback(self):
        for failure in [False,True]:
            with tempfile.TemporaryDirectory() as tmp:
                root=pathlib.Path(tmp);self.fixture(root)
                env=(root/'.env').read_bytes()
                inode=(root/'config/db-password').stat().st_ino
                payload={name: b'new file' for name in module.FILES}
                payload['VERSION']=b'0.2.0\n'
                payload['manage.sh']=b'#!/bin/sh\nexit '+(b'1' if failure else b'0')+b'\n'
                if failure:
                    with self.assertRaises(Exception): module.upgrade(root,'0.2.0',payload)
                    self.assertEqual((root/'VERSION').read_text(),'0.1.5\n')
                    self.assertEqual((root/'.env').read_bytes(),env)
                else:
                    module.upgrade(root,'0.2.0',payload)
                    text=(root/'.env').read_text()
                    self.assertIn('MOFIS_DEPLOY_VERSION=0.2.0',text)
                    self.assertIn('COMPOSE_PROJECT_NAME=original',text)
                    self.assertIn('PG_DATA_VOLUME=original_pgdata',text)
                    self.assertIn('SSH_PORT=2223',text)
                self.assertEqual((root/'config/db-password').read_text(),'secret')
                self.assertEqual((root/'config/db-password').stat().st_ino,inode)
                self.assertEqual((root/'connection.txt').read_text(),'private connection')
                self.assertTrue(list((root/'.upgrade-backups').glob('*/.env')))

    def test_pending_recovery_and_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);self.fixture(root)
            (root/'config/reset-db-password').touch()
            with self.assertRaises(ValueError): module.upgrade(root,'0.2.0',{})
            module.upgrade(root,'0.1.4',{})
            self.assertEqual((root/'VERSION').read_text(),'0.1.5\n')

    def test_reject_major_database_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);self.fixture(root)
            (root/'compose.postgres.yaml').write_text('image: postgres:16-alpine\n')
            with self.assertRaises(ValueError):
                module.upgrade(root,'0.2.0',{'compose.postgres.yaml':b'image: postgres:17-alpine\n'})
            self.assertFalse((root/'.upgrade-backups').exists())
            self.assertEqual((root/'VERSION').read_text(),'0.1.5\n')

if __name__ == '__main__':
    unittest.main()
