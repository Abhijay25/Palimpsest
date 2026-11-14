"""Viewer boundary checks. No database, inference, network or paid calls."""
import unittest
from explore_preview import app
from discrepancy_explorer import snapshot_rows


class ExplorerTests(unittest.TestCase):
    def test_page_works_without_database(self):
        with app.test_client() as client:
            response=client.get('/explore')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'id="matrix-scroll"',response.data)
        self.assertIn(b'Divergence Temporal Matrix',response.data)
        self.assertIn(b'/static/lab-explorer.js',response.data)

    def test_constellation_remains_independently_accessible(self):
        with app.test_client() as client:response=client.get('/explore?layout=constellation')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'id="constellation-screen"',response.data)
        self.assertIn(b'/static/constellation.js',response.data)

    def test_invalid_topic_never_reaches_database(self):
        with app.test_client() as client:
            response=client.get('/explore/api/cached?topic=Q1%27%20OR%201=1')
        self.assertEqual(response.status_code,400)

    def test_snapshots_do_not_invent_intervals_or_groups(self):
        finding=dict(id='real-snapshot',category='conflict',title='Inspect values',evidence=[
            dict(lang='en',quote='<script>not markup</script> 2000',rev_id=42),
            dict(lang='sv',quote='1999',rev_id=43)])
        rows=snapshot_rows([finding],'2025-08-01T12:00:00Z',['en','sv'])
        self.assertFalse(rows[0]['grouped'])
        phase=rows[0]['phases'][0]
        self.assertTrue(phase['snapshot'])
        self.assertEqual(phase['start'],phase['end'])
        self.assertEqual(phase['evidence'][0]['quote'],finding['evidence'][0]['quote'])
        self.assertTrue(phase['evidence'][0]['url'].endswith('oldid=42'))

    def test_equivalent_and_single_edition_findings_hidden(self):
        evidence=[dict(lang='en',quote='same'),dict(lang='fi',quote='sama')]
        self.assertEqual(snapshot_rows([dict(category='same',evidence=evidence)],'2025-01-01',['en','fi']),[])
        self.assertEqual(snapshot_rows([dict(category='uncertain',evidence=evidence)],'2025-01-01',['en','fi']),[])
        self.assertEqual(snapshot_rows([dict(category='conflict',evidence=evidence)],'2025-01-01',['en','sv']),[])


if __name__=='__main__':unittest.main()
