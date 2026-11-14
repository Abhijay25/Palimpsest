"""Seed contracts only: no downloads, external DB, models or API requests."""
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from deploy import seed_bge_catalog as s


def source():
    return dict(lang='fi', page_id=42, rev_id=99, wikidata_id='Q134949', title='Talvisota',
                url='https://fi.wikipedia.org/wiki/Talvisota', date_modified='2025-07-29T12:00:00Z', text='Exact source')


def vector():
    return dict(lang='fi', page_id=42, model='bge-m3', truncated=False, embedding=[.1] * 1024)


class SeedBgeTests(unittest.TestCase):
    def test_scope_must_be_explicit_and_positive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in ([], ['--limit', '0'], ['--all', '--limit', '20']):
                with self.assertRaises(SystemExit):
                    s.parser().parse_args(args)
        self.assertEqual(s.parser().parse_args(['--limit', '20']).limit, 20)

    def test_source_identity_and_exact_anchor_preserved(self):
        row = s.normalize(source(), vector(), 'fi')
        self.assertEqual(row['topic_id'], 'Q134949')
        self.assertEqual(row['source_page_id'], 42)
        self.assertEqual(row['source_revision_id'], 99)
        self.assertEqual(row['text_hash'], hashlib.sha256(b'Exact source').hexdigest())
        self.assertEqual(row['identity_kind'], 'wikidata')

    def test_unlinked_source_namespace_does_not_invent_wikidata_id(self):
        article = source()
        article['wikidata_id'] = None
        row = s.normalize(article, vector(), 'fi')
        self.assertEqual(row['topic_id'], 'fi:42')
        self.assertEqual(row['identity_kind'], 'source_page')

    def test_model_dimensions_and_nonfinite_refused(self):
        for change in (dict(model='intfloat/multilingual-e5-small'), dict(embedding=[.1] * 384),
                       dict(embedding=[math.nan] * 1024), dict(embedding=[0.] * 1024), dict(truncated=None)):
            bad = {**vector(), **change}
            with self.assertRaises(ValueError):
                s.normalize(source(), bad, 'fi')

    def test_wrong_join_or_anchor_metadata_refused(self):
        for change in (dict(lang='en'), dict(page_id=7), dict(rev_id=0), dict(wikidata_id='invented'),
                       dict(url='https://example.org/wiki/Talvisota'), dict(date_modified='invalid')):
            with self.assertRaises(ValueError):
                s.normalize({**source(), **change}, vector(), 'fi')

    def test_matching_asset_reused_without_network(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'asset.parquet').write_bytes(b'locked')
            asset = dict(name='asset.parquet', size=6, sha256=hashlib.sha256(b'locked').hexdigest(), url='unused')
            with patch.object(s.urllib.request, 'urlopen') as request:
                self.assertEqual(s.asset_file(asset, folder), folder / 'asset.parquet')
            request.assert_not_called()

    def test_bad_download_never_publishes_asset(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            asset = dict(name='asset.parquet', size=6, sha256=hashlib.sha256(b'locked').hexdigest(), url='https://example.org/a')
            response = MagicMock()
            response.__enter__.return_value = io.BytesIO(b'wrong!')
            with patch.object(s, 'disk_guard'), patch.object(s.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    s.asset_file(asset, folder)
            self.assertFalse((folder / 'asset.parquet').exists())
            self.assertFalse((folder / 'asset.parquet.part').exists())

    def test_current_repo_lock_is_valid_without_network(self):
        lock, checksum = s.read_lock(s.default_lock_path())
        self.assertEqual(lock['tag'], 's-2026-10')
        self.assertEqual(len(checksum), 64)
        self.assertEqual(sum(lock['expected_counts'].values()), 29460)

    def test_publication_and_provenance_commit_together(self):
        db, c = MagicMock(), MagicMock()
        row = s.normalize(source(), vector(), 'fi')
        s.publish(db, c, [row], dict(tag='s-2026-10'), 'a' * 64)
        db.begin.assert_called_once()
        db.commit.assert_called_once()
        self.assertEqual(c.executemany.call_count, 2)
        first = c.executemany.call_args_list[0].args
        self.assertIn('VEC_FromText', first[0])
        self.assertEqual(first[1][0][:4], ('Q134949', 'fi', 42, 99))
        self.assertEqual(len(json.loads(first[1][0][-1])), 1024)

    def test_failed_batch_rolls_back(self):
        db, c = MagicMock(), MagicMock()
        c.executemany.side_effect = [None, RuntimeError('test')]
        with self.assertRaises(RuntimeError):
            s.publish(db, c, [s.normalize(source(), vector(), 'fi')], dict(tag='s-2026-10'), 'a' * 64)
        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_schema_is_main_compatible_and_separate(self):
        c = MagicMock()
        s.init(c)
        sql = '\n'.join(call.args[0] for call in c.execute.call_args_list)
        self.assertIn('embedding VECTOR(1024)', sql)
        self.assertIn('M=16 DISTANCE=cosine', sql)
        self.assertIn('PRIMARY KEY(language,source_page_id)', sql)
        self.assertNotIn('CREATE TABLE IF NOT EXISTS passage ', sql)

    def test_research_database_configuration_fails_closed(self):
        with patch.dict(s.os.environ, {'DB_NAME': 'language_gaps'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'DB_NAME=library'):
                s.connect()

    def test_local_windows_seed_does_not_download_or_connect(self):
        with patch.object(s.sys, 'argv', ['seed_bge_catalog.py', '--all']), \
             patch.object(s.sys, 'platform', 'win32'), patch.object(s, 'seed') as seed, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.main(), 1)
        seed.assert_not_called()

    def test_shallow_docker_module_path_defaults_to_mounted_lock(self):
        with patch.object(Path, 'is_file', return_value=False):
            self.assertEqual(s.default_lock_path('/app/deploy/seed_bge_catalog.py'), Path('/run/datasets.lock.json'))

    def test_module_import_with_actual_shallow_docker_file_identity(self):
        namespace = {'__file__': '/app/deploy/seed_bge_catalog.py', '__name__': 'docker_import_probe'}
        code = compile(Path(s.__file__).read_text(encoding='utf-8'), namespace['__file__'], 'exec')
        with patch.object(Path, 'is_file', return_value=False):
            exec(code, namespace)
            args = namespace['parser']().parse_args(['--limit', '20'])
        self.assertEqual(args.lock, Path('/run/datasets.lock.json'))

    def test_mounted_lock_override_is_available_without_repository(self):
        with patch.object(s, 'default_lock_path', return_value=Path('/run/datasets.lock.json')):
            self.assertEqual(s.parser().parse_args(['--all']).lock, Path('/run/datasets.lock.json'))
            self.assertEqual(s.parser().parse_args(['--all', '--lock', '/data/lock.json']).lock, Path('/data/lock.json'))

    def test_static_validation_diagnostic_is_actionable(self):
        output = io.StringIO()
        with patch.object(s.sys, 'argv', ['seed_bge_catalog.py', '--all']), \
             patch.object(s.sys, 'platform', 'linux'), \
             patch.object(s, 'seed', side_effect=s.SeedValidationError('Asset checksum/size mismatch; nothing imported.')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(s.main(), 1)
        self.assertIn('checksum/size mismatch', json.loads(output.getvalue())['message'])

    def test_external_error_details_are_not_exposed(self):
        output = io.StringIO()
        with patch.object(s.sys, 'argv', ['seed_bge_catalog.py', '--all']), \
             patch.object(s.sys, 'platform', 'linux'), \
             patch.object(s, 'seed', side_effect=RuntimeError('sensitive private connection value')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(s.main(), 1)
        self.assertNotIn('sensitive', output.getvalue())


if __name__ == '__main__':
    unittest.main()
