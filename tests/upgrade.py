"""Exercise upgrades without customer databases or network access."""
import hashlib
import importlib.util
import io
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
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
    def test_cloudflare_download(self):
        calls = []
        def fetch(url, timeout=60):
            calls.append(url)
            if url.endswith('latest.json'): return b'{"version":"0.2.0"}'
            return b'zip' if url.endswith('.zip') else b'sums'
        with patch.object(module, 'fetch', side_effect=fetch):
            self.assertEqual(module.download_release(), (b'zip', 'sums', '0.2.0'))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(url.startswith(module.MIRROR) for url in calls))

    def test_fallback_keeps_discovered_version_and_checksum_source(self):
        calls = []
        def fetch(url, timeout=60):
            calls.append(url)
            if url.endswith('latest.json'): return b'{"version":"0.2.0"}'
            if url.startswith(module.MIRROR):
                if url.endswith('.zip'): return b'incomplete-mirror'
                raise urllib.error.URLError('offline')
            return b'github-zip' if url.endswith('.zip') else b'github-sums'
        with patch.object(module, 'fetch', side_effect=fetch):
            self.assertEqual(module.download_release(), (b'github-zip', 'github-sums', '0.2.0'))
        self.assertNotIn('api.github.com', ' '.join(calls))
        self.assertTrue(all('/v0.2.0/' in url for url in calls if 'github.com' in url))

    def test_explicit_source_and_invalid_metadata(self):
        with patch.object(module, 'fetch', side_effect=urllib.error.URLError('offline')) as fetch:
            with self.assertRaises(urllib.error.URLError): module.download_release('0.2.0', 'cloudflare')
            self.assertEqual(fetch.call_count, 1)
        with patch.object(module, 'fetch', return_value=b'{"version":"../../bad"}') as fetch:
            with self.assertRaises(ValueError): module.download_release()
            self.assertEqual(fetch.call_count, 1)
        with patch.object(module, 'fetch', return_value=b'file') as fetch:
            module.download_release('0.2.0', 'github')
            self.assertTrue(all('github.com' in c.args[0] for c in fetch.call_args_list))

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
        (root/'.env').write_text('DEPLOY_MODE=full\nCOMPOSE_PROJECT_NAME=original\nPG_DATA_VOLUME=original_pgdata\nSSH_PORT=2223\nMOFIS_DEPLOY_VERSION=0.1.5\n')
        (root/'config').mkdir()
        (root/'config/db-password').write_text('secret')
        (root/'config/db-ca.crt').write_text('saved CA certificate')
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
                    self.assertIn('COMPOSE_PROFILES=managed-db',text)
                self.assertEqual((root/'config/db-password').read_text(),'secret')
                self.assertEqual((root/'config/db-password').stat().st_ino,inode)
                self.assertEqual((root/'config/db-ca.crt').read_text(),'saved CA certificate')
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
            (root/'compose.yaml').write_text('image: postgres:16-alpine\n')
            with self.assertRaises(ValueError):
                module.upgrade(root,'0.2.0',{'compose.yaml':b'image: postgres:17-alpine\n'})
            self.assertFalse((root/'.upgrade-backups').exists())
            self.assertEqual((root/'VERSION').read_text(),'0.1.5\n')

if __name__ == '__main__':
    unittest.main()
