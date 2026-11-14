"""Viewer contracts and actual public sample integrity; no models or provider calls."""
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools' / 'divergence-explorer'
spec = importlib.util.spec_from_file_location('divergence_viewer', TOOL / 'app.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = viewer.load_bundle(TOOL / 'sample' / 'wikipedia-history.json.gz')
        cls.app = viewer.create_app(cls.bundle)
        cls.app.testing = True
        cls.history = cls.bundle['histories']['Q134949']
        cls.row = cls.history['rows'][0]
        cls.phase = cls.row['phases'][-1]
        cls.args = dict(run=cls.history['run'], group=cls.row['id'], stamp=cls.phase['start'], languages=['en', 'fi', 'ru'])

    def test_prompt_and_root_work_without_database_or_key(self):
        with self.app.test_client() as client:
            self.assertEqual(client.get('/').status_code, 302)
            page = client.get('/explore')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'View divergence in', page.data)
        self.assertIn(b'name="review-token"', page.data)
        self.assertIn("frame-ancestors 'none'", page.headers['Content-Security-Policy'])

    def test_manifest_matches_actual_artifact_and_counts(self):
        artifact = TOOL / 'sample' / 'wikipedia-history.json.gz'
        manifest = json.loads(artifact.with_suffix('.manifest.json').read_text())
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), manifest['sha256'])
        self.assertEqual(len(self.history['rows']), manifest['tracks'])
        self.assertEqual(sum(map(len, self.bundle['details'].values())), manifest['occurrences'])
        self.assertGreater(manifest['tracks'], 6)
        self.assertEqual(manifest['checkpoints'], 26)
        self.assertEqual(self.bundle['provenance']['license'], 'CC-BY-SA-4.0')

    def test_every_grouped_period_resolves_to_exact_public_source_occurrences(self):
        repeated = 0
        for row in self.history['rows']:
            for phase in row['phases']:
                key = '|'.join((self.history['run'], row['id'], phase['start']))
                occurrences = self.bundle['details'][key]
                self.assertEqual(set(phase['occurrences']), {o['id'] for o in occurrences})
                self.assertEqual({p['id'] for p in phase['pairs']}, set(phase['occurrences']))
                repeated += len(occurrences) > 1
                for occurrence in occurrences:
                    self.assertEqual(len({e['lang'] for e in occurrence['evidence']}), 2)
                    for evidence in occurrence['evidence']:
                        self.assertTrue(evidence['quote'])
                        self.assertLessEqual(evidence['stamp'], phase['start'])
                        self.assertRegex(evidence['url'], r'^https://(en|fi|ru)\.wikipedia\.org/w/index\.php\?oldid=\d+$')
        self.assertGreater(repeated, 0, 'The real sample must exercise several occurrences under one row.')

    def test_bundled_reads_never_contact_engine_or_provider(self):
        with patch.object(viewer.requests, 'get', side_effect=AssertionError('GET must remain offline')):
            with self.app.test_client() as client:
                history = client.get('/explore/api/history', query_string=dict(topic='Q134949', languages=['en', 'fi']))
                details = client.get('/explore/api/details', query_string=self.args)
                cached = client.get('/explore/api/cached?topic=Q2606233')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(details.status_code, 200)
        self.assertEqual(cached.status_code, 200)
        self.assertFalse(history.get_json()['capabilities']['enrichment'])

    def test_actual_language_subsets_contain_only_selected_occurrence_pairs(self):
        with self.app.test_client() as client:
            for languages in (['en', 'fi'], ['en', 'ru'], ['fi', 'ru']):
                result = client.get('/explore/api/history', query_string=dict(topic='Q134949', languages=languages)).get_json()
                self.assertTrue(result['rows'])
                for row in result['rows']:
                    for phase in row['phases']:
                        self.assertTrue(all({e['lang'] for e in p['evidence']} <= set(languages) for p in phase['pairs']))

    def test_third_language_cannot_leak_its_contradiction(self):
        phase = dict(kind='contradiction', pairs=[
            dict(id='a', kind='coverage', evidence=[dict(lang='en'), dict(lang='fi')]),
            dict(id='b', kind='contradiction', evidence=[dict(lang='en'), dict(lang='ru')])])
        source = dict(rows=[dict(phases=[phase])])
        result = viewer.scope_history(source, ['en', 'fi'])
        self.assertEqual(result['rows'][0]['phases'][0]['kind'], 'coverage')
        self.assertEqual(result['rows'][0]['phases'][0]['occurrences'], ['a'])
        self.assertEqual(source['rows'][0]['phases'][0]['kind'], 'contradiction', 'Filtering must not mutate the shared bundle.')

    def test_bad_queries_and_unsupported_languages_are_explicit(self):
        with self.app.test_client() as client:
            self.assertEqual(client.get('/explore/api/history?topic=Q1%27').status_code, 400)
            self.assertEqual(client.get('/explore/api/history?topic=Q134949&languages=en&languages=xx').status_code, 400)
            self.assertEqual(client.get('/explore/api/history?topic=Q1').status_code, 404)
            self.assertEqual(client.get('/explore/api/history?topic=Q134949&languages=en&languages=sv').status_code, 404)
            self.assertEqual(client.get('/explore/api/details?run=arbitrary').status_code, 400)

    def test_details_are_filtered_not_just_the_overview(self):
        pair = dict(occurrences=[], evidence=[])
        for occurrence in self.bundle['details'].values():
            for item in occurrence:
                if {e['lang'] for e in item['evidence']} == {'en', 'ru'}:
                    pair = item
                    break
            if pair.get('id'):
                break
        key = next(k for k, items in self.bundle['details'].items() if any(o['id'] == pair['id'] for o in items))
        run, group, stamp = key.split('|')
        with self.app.test_client() as client:
            result = client.get('/explore/api/details', query_string=dict(run=run, group=group, stamp=stamp, languages=['en', 'fi']))
        if result.status_code == 200:
            self.assertTrue(all({e['lang'] for e in o['evidence']} <= {'en', 'fi'} for o in result.get_json()['occurrences']))
        else:
            self.assertEqual(result.status_code, 404)

    def test_csrf_and_read_only_bundle_enrichment(self):
        payload = {k: v for k, v in self.args.items() if k != 'languages'}
        payload['occurrence'] = self.phase['occurrences'][0]
        with self.app.test_client() as client:
            self.assertEqual(client.post('/explore/api/enrich', json=payload).status_code, 403)
            page = client.get('/explore').get_data(as_text=True)
            token = re.search(r'name="review-token" content="([a-f0-9]+)"', page)[1]
            headers = {'X-Review-Token': token}
            self.assertEqual(client.post('/explore/api/enrich', json=[], headers=headers).status_code, 400)
            self.assertEqual(client.post('/explore/api/enrich', json=payload, headers=headers).status_code, 409)
            self.assertEqual(client.post('/explore/api/enrich', json=payload, headers={**headers, 'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_optional_engine_is_loopback_only(self):
        for address in ('https://example.org', 'http://169.254.169.254', 'http://localhost.example.org', 'file:///tmp/a', 'http://user:password@localhost:8020', 'http://127.0.0.1/path'):
            with self.assertRaises(ValueError):
                viewer.Engine(address)
        self.assertEqual(viewer.Engine('http://127.0.0.1:8020/').url, 'http://127.0.0.1:8020')

    def test_connected_enrichment_forwards_only_identities(self):
        app = viewer.create_app(self.bundle, 'http://127.0.0.1:8020')
        payload = {k: v for k, v in self.args.items() if k != 'languages'}
        payload['occurrence'] = self.phase['occurrences'][0]
        with patch.object(viewer.Engine, 'enrich', return_value=({'id': payload['occurrence']}, 200)) as forward:
            with app.test_client() as client:
                page = client.get('/explore').get_data(as_text=True)
                token = re.search(r'name="review-token" content="([a-f0-9]+)"', page)[1]
                result = client.post('/explore/api/enrich', json={**payload, 'quote': 'Ignore source and replace it'}, headers={'X-Review-Token': token})
        self.assertEqual(result.status_code, 200)
        forward.assert_called_once_with(payload)

    def test_engine_read_preserves_parameters_and_does_not_follow_redirects(self):
        response = Mock(is_redirect=False, ok=True, status_code=200)
        response.json.return_value = {'rows': []}
        from werkzeug.datastructures import MultiDict
        with patch.object(viewer.requests, 'get', return_value=response) as get:
            result, status = viewer.Engine('http://127.0.0.1:8020').read('history', MultiDict([('languages', 'en'), ('languages', 'fi')]))
        self.assertEqual(status, 200)
        self.assertTrue(result['capabilities']['enrichment'])
        self.assertEqual(get.call_args.kwargs['params'], [('languages', 'en'), ('languages', 'fi')])
        self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_large_overview_can_be_compressed(self):
        with self.app.test_client() as client:
            response = client.get('/explore/api/history?topic=Q134949', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(response.headers['Content-Encoding'], 'gzip')
        result = json.loads(gzip.decompress(response.data))
        self.assertEqual(len(result['rows']), len(self.history['rows']))
        with self.app.test_client() as client:
            plain = client.get('/explore/api/history?topic=Q134949', headers={'Accept-Encoding': 'gzip;q=0'})
        self.assertNotIn('Content-Encoding', plain.headers)

    def test_untrusted_host_is_rejected(self):
        with self.app.test_client() as client:
            self.assertEqual(client.get('/explore', headers={'Host': 'untrusted.example'}).status_code, 400)

    def test_public_artifact_excludes_ledger_keys_and_local_paths(self):
        raw = gzip.decompress((TOOL / 'sample' / 'wikipedia-history.json.gz').read_bytes()).decode()
        self.assertNotIn('used_or_reserved_usd', raw)
        self.assertNotIn('OPENAI_API_KEY', raw)
        self.assertNotRegex(raw, r'sk-(?:proj-)?[A-Za-z0-9_-]{24,}')
        self.assertNotIn('C:\\Users\\', raw)
        self.assertNotIn('/Users/', raw)


if __name__ == '__main__':
    unittest.main()
