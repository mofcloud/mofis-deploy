"""Check release mirror ordering and integrity without credentials or R2 writes."""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('publisher', ROOT/'scripts/publish-r2.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
upgrade_spec = importlib.util.spec_from_file_location('upgrade_tests', ROOT/'tests/upgrade.py')
upgrade_tests = importlib.util.module_from_spec(upgrade_spec)
upgrade_spec.loader.exec_module(upgrade_tests)

class MissingObject(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}

class Client:
    def __init__(self, latest=None):
        self.writes = []
        self.latest = latest
    def put_object(self, **args): self.writes.append(args)
    def get_object(self, **args):
        if not self.latest: raise MissingObject()
        return {'Body': io.BytesIO(json.dumps({'version': self.latest}).encode())}

class PublishTests(unittest.TestCase):
    def test_verified_files_before_latest(self):
        data, sums = upgrade_tests.bundle()
        for latest in [None, '0.3.0']:
            with tempfile.TemporaryDirectory() as tmp:
                directory = pathlib.Path(tmp)
                (directory/'mofis-deploy-0.2.0.zip').write_bytes(data)
                (directory/'SHA256SUMS').write_text(sums)
                client = Client(latest)
                with patch.object(publisher, 'fetch', side_effect=[data, sums.encode()]):
                    publisher.publish(client, 'bucket', 'https://data.example.com', '0.2.0', directory)
                self.assertEqual([x['Key'] for x in client.writes[:2]], ['mofis-deploy/0.2.0/mofis-deploy-0.2.0.zip', 'mofis-deploy/0.2.0/SHA256SUMS'])
                if latest:
                    self.assertEqual(len(client.writes), 2)
                else:
                    self.assertEqual(client.writes[-1]['Key'], 'mofis-deploy/latest.json')
                    self.assertEqual(client.writes[-1]['CacheControl'], 'no-store, max-age=0')
                client = Client()
                with patch.object(publisher, 'fetch', side_effect=[b'corrupt', sums.encode()]):
                    with self.assertRaises(ValueError): publisher.publish(client, 'bucket', 'https://data.example.com', '0.2.0', directory)
                self.assertEqual(len(client.writes), 2)

if __name__ == '__main__': unittest.main()
