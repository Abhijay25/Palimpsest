import unittest
from unittest.mock import Mock
from scripts.verify_native_page_fixture import fixture_dispatch


class NativePageFixtureTests(unittest.TestCase):
    def test_only_exact_verified_success_is_decorated_without_mutating_saved_evidence(self):
        saved = dict(status='ok', flags=[], page_html='Real native HTML', _issue_assessment='real-id')
        original = Mock(return_value=saved)
        read = fixture_dispatch(original, 1301539037)
        payload = dict(op='cached', mode='page', edition='en', title='Winter War',
                       source=dict(revision_id=1301539037))
        result = read(payload)
        self.assertTrue(result['verification_fixture'])
        self.assertEqual(len(result['flags']), 2)
        self.assertTrue(all(f['title'].startswith('UI FIXTURE ONLY') for f in result['flags']))
        self.assertNotIn('_issue_assessment', result)
        self.assertEqual(saved['flags'], [])
        self.assertEqual(saved['_issue_assessment'], 'real-id')
        self.assertIs(read(dict(payload, source=dict(revision_id=1301539038))), saved)
        self.assertIs(read(dict(payload, mode='revision')), saved)
        original.return_value = dict(status='unavailable')
        with self.assertRaises(LookupError):
            read(payload)

    def test_all_mutations_are_rejected_before_production_dispatch(self):
        original = Mock()
        read = fixture_dispatch(original, 1301539037)
        for operation in ['scan', 'review']:
            with self.assertRaises(LookupError):
                read(dict(op=operation))
        original.assert_not_called()
        with self.assertRaises(ValueError):
            fixture_dispatch(original, 7)


if __name__ == '__main__':
    unittest.main()
