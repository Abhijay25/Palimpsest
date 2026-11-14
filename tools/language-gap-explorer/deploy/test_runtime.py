"""No-network packaging checks; WSGI policy runs in an isolated subprocess."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import runtime


class RuntimeTests(unittest.TestCase):
    def test_compose_tmpfs_options_are_one_mount(self):
        import yaml
        path = Path(__file__).resolve().parents[1] / 'compose.vps.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        self.assertEqual(config['services']['web']['tmpfs'], ['/tmp:rw,nosuid,nodev,size=128m'])
        self.assertNotIn('OPENAI_API_KEY_FILE', config['services']['embedding-worker']['environment'])
        self.assertEqual(config['services']['catalog-seed']['environment']['DB_NAME'], 'library')

    def test_reader_loads_secret_files_but_strips_provider_keys(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'password').write_text('test-only-db-password', encoding='utf-8')
            (root / 'session').write_text('s' * 64, encoding='utf-8')
            with patch.dict(os.environ, {
                'NEOWIKI_ROLE': 'reader', 'NEOWIKI_RESEARCH_ROOT': folder,
                'DB_PASSWORD_FILE': str(root / 'password'),
                'NEOWIKI_SESSION_SECRET_FILE': str(root / 'session'),
                'OPENAI_API_KEY': 'must-be-stripped', 'OPEN_API_KEY': 'also-stripped',
            }, clear=True):
                runtime.configure()
                self.assertEqual(os.environ['DB_PASSWORD'], 'test-only-db-password')
                self.assertEqual(os.environ['NEOWIKI_SESSION_SECRET'], 's' * 64)
                self.assertNotIn('OPENAI_API_KEY', os.environ)
                self.assertNotIn('OPEN_API_KEY', os.environ)

    def test_reader_rejects_runtime_root_environment_file(self):
        with TemporaryDirectory() as folder:
            (Path(folder) / '.env').write_text('not-a-secret', encoding='utf-8')
            with patch.dict(os.environ, {
                'NEOWIKI_ROLE': 'reader', 'NEOWIKI_RESEARCH_ROOT': folder,
                'DB_PASSWORD': 'test-only', 'NEOWIKI_SESSION_SECRET': 's' * 64,
            }, clear=True):
                with self.assertRaisesRegex(RuntimeError, 'environment files'):
                    runtime.configure()

    def test_worker_requires_its_own_provider_secret(self):
        with patch.dict(os.environ, {'NEOWIKI_ROLE': 'worker', 'DB_PASSWORD': 'test-only'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'OPENAI_API_KEY'):
                runtime.configure()

    def test_empty_secret_fails_without_logging_contents(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'empty'
            path.write_text('', encoding='utf-8')
            with patch.dict(os.environ, {'DB_PASSWORD_FILE': str(path)}, clear=True):
                with self.assertRaisesRegex(RuntimeError, 'empty: DB_PASSWORD'):
                    runtime.load_secret('DB_PASSWORD', required=True)

    def test_public_reader_policy_in_isolated_process(self):
        code = r'''
import os
from unittest.mock import patch, MagicMock
os.environ['NEOWIKI_SESSION_SECRET'] = 'test-only-session-secret-at-least-32-characters'
os.environ['NEOWIKI_COOKIE_SECURE'] = '0'
from deploy import wsgi
client = wsgi.app.test_client()
assert client.get('/').location == '/explore'
assert client.get('/explore').status_code == 200
assert wsgi.app.secret_key == os.environ['NEOWIKI_SESSION_SECRET']
for method, path in [
    ('get', '/reviews'), ('get', '/explore/api/history?topic=Q134949'),
    ('get', '/explore/api/details'), ('get', '/explore/api/cached?topic=Q134949'),
    ('post', '/reviews/Q134949'), ('post', '/explore/api/enrich'),
    ('post', '/topic/Q134949/verify'), ('get', '/langcompare/Q134949?demo=1'),
    ('post', '/watchlist/links'), ('post', '/unknown-future-preparation-route'),
]:
    response = getattr(client, method)(path)
    assert response.status_code == 404, (path, response.status_code)
assert client.post('/translations', json={'lang':'fi', 'text':'test'}).status_code == 403
with client.session_transaction() as session:
    token = session['review_token']
with patch('local_translation.translate', return_value={'text':'local-only', 'cached':True}) as translate:
    response = client.post('/translations', json={'lang':'fi','text':'test'}, headers={'X-Review-Token':token})
    assert response.status_code == 200 and response.json['text'] == 'local-only'
    translate.assert_called_once_with('test', 'fi')
with patch.object(wsgi, 'connect') as connect:
    connect.return_value.__enter__.return_value = MagicMock()
    assert client.get('/healthz').json['status'] == 'ready'
with patch.object(wsgi, 'connect', side_effect=RuntimeError('private-detail')):
    response = client.get('/healthz')
    assert response.status_code == 503 and 'private-detail' not in response.get_data(as_text=True)
try:
    wsgi.live_api.call('unused', {}, 'unused')
except wsgi.live_api.APIError:
    pass
else:
    raise AssertionError('The public reader can call a provider.')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_schema_initializers_exist_without_running_them(self):
        from importlib import import_module
        from deploy.init_schema import INITIALIZERS
        self.assertNotIn(('assessment_state', 'init'), INITIALIZERS)
        for module, name in INITIALIZERS:
            self.assertTrue(callable(getattr(import_module(module), name)))


if __name__ == '__main__':
    unittest.main()
