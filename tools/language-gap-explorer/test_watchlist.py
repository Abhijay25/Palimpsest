import json,unittest,uuid
from unittest.mock import patch
from core import connect
import watchlist as w

class WatchlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):w.init()

    def setUp(self):
        self.topic='Q'+str(900000000+int(uuid.uuid4().hex[:7],16))
        self.quotes={'en':'The town had 1000 residents in 2020.',
                     'fi':'Kaupungissa oli 1000 asukasta vuonna 2020.'}
        with connect() as db,db.cursor() as c:
            for lang,quote in self.quotes.items():
                c.execute('INSERT INTO article VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                  (lang,999999999,111,self.topic,'Watch test '+lang,'https://example.invalid','2025-01-01','# Test\n'+quote+'\n\nUnrelated text.'))
        self.docs=w.ensure_topic(self.topic)
        self.link=w.create_link(self.topic,[{'lang':l,'quote':q} for l,q in self.quotes.items()],
            'Population in 2020','Same population measure and year.')

    def tearDown(self):
        with connect() as db,db.cursor() as c:
            c.execute('DELETE r FROM watched_review r JOIN watched_notice n ON r.notice_id=n.id JOIN watched_link l ON n.link_id=l.id WHERE l.topic=%s',(self.topic,))
            c.execute('DELETE n FROM watched_notice n JOIN watched_link l ON n.link_id=l.id WHERE l.topic=%s',(self.topic,))
            c.execute('DELETE FROM watched_link WHERE topic=%s',(self.topic,))
            c.execute('DELETE r FROM watched_revision r JOIN watched_document d ON r.document_id=d.id WHERE d.topic=%s',(self.topic,))
            c.execute('DELETE FROM watched_document WHERE topic=%s',(self.topic,))
            c.execute('DELETE FROM review_passage WHERE topic=%s',(self.topic,))
            c.execute('DELETE FROM article WHERE wikidata_id=%s',(self.topic,))

    def edit(self,lang,text):
        doc=w.documents(self.topic)[lang]
        return w.ingest(self.topic,lang,text,doc['current_revision'])

    def test_link_confirmation_is_idempotent(self):
        again=w.create_link(self.topic,[{'lang':l,'quote':q} for l,q in self.quotes.items()],'Same','Same')
        self.assertEqual(again,self.link)

    def test_unrelated_edits_and_moves_do_not_notify(self):
        old=self.docs['en']['text']
        with patch('live_api.requests.post',side_effect=AssertionError('No API allowed')):
            _,count=self.edit('en',old+'\nAn unrelated addition.')
            self.assertEqual(count,0)
            new='Heading changed.\n\n'+self.quotes['en']
            _,count=self.edit('en',new)
            self.assertEqual(count,0)
        self.assertEqual(w.overview(self.topic)[0],[])

    def test_numeric_change_notifies_and_reviews_persist(self):
        with patch('live_api.requests.post',side_effect=AssertionError('No API allowed')):
            revision,count=self.edit('en',self.docs['en']['text'].replace('1000','1100'))
            self.assertEqual(count,1)
            notices,_=w.overview(self.topic);n=notices[0]
            self.assertEqual(n['kind'],'value_changed')
            self.assertIn('1000',n['data']['before']);self.assertIn('1100',n['data']['after'])
            w.review(n['id'],'needs_update','Finnish needs source verification.')
            self.assertEqual(w.overview(self.topic)[0][0]['status'],'needs_update')
            w.review(n['id'],'already_covered','Checked the scope; no further change needed.')
            notices,links=w.overview(self.topic)
            self.assertEqual(notices[0]['status'],'already_covered')
            side=next(s for s in links[0]['sides'] if s['lang']=='en')
            self.assertEqual(side['baseline_revision'],revision)
            self.assertIn('1100',side['baseline_text'])

    def test_bidirectional_edits_supersede_old_notification(self):
        self.edit('en',self.docs['en']['text'].replace('1000','1100'))
        self.edit('fi',self.docs['fi']['text'].replace('1000','1200'))
        notices,_=w.overview(self.topic)
        self.assertEqual(sum(n['status']=='pending' for n in notices),1)
        self.assertEqual(sum(n['status']=='superseded' for n in notices),1)
        self.assertEqual(next(n for n in notices if n['status']=='pending')['lang'],'fi')
        old=next(n for n in notices if n['status']=='superseded')
        with self.assertRaises(w.StaleRevision):w.review(old['id'],'no_update','Outdated review')

    def test_stale_revision_does_not_overwrite(self):
        self.edit('en',self.docs['en']['text'].replace('1000','1100'))
        with self.assertRaises(w.StaleRevision):
            w.ingest(self.topic,'en','Overwrite',self.docs['en']['current_revision'])
        self.assertIn('1100',w.documents(self.topic)['en']['text'])

    def test_import_preserves_upstream_provenance_and_snapshots(self):
        revision,count=w.ingest(self.topic,'fi',self.docs['fi']['text'].replace('1000','1200'),
            self.docs['fi']['current_revision'],kind='imported',upstream_id='wiki-revision-222',label='Test import')
        self.assertEqual(count,1)
        document=w.documents(self.topic)['fi']
        self.assertEqual(document['upstream_id'],'wiki-revision-222')
        self.assertEqual(document['kind'],'imported')
        with connect() as db,db.cursor() as c:
            c.execute('SELECT text FROM article WHERE wikidata_id=%s AND lang=%s',(self.topic,'fi'))
            self.assertIn('1000',c.fetchone()['text'])
        self.assertEqual(w.overview(self.topic)[0][0]['changed_revision'],revision)

    def test_optional_decisions_check_does_not_advance_baseline(self):
        self.edit('en',self.docs['en']['text'].replace('1000','1100'))
        notice=w.overview(self.topic)[0][0]
        from app import app
        client=app.test_client();client.get('/watchlist')
        with client.session_transaction() as session:token=session['review_token']
        result={name:{'type':'predicate','name':name,'probability':0.9} for name in ('factual_change','counterpart_affected')}
        with patch('live_api.decisions',return_value=result) as decision:
            response=client.post('/watchlist/notices/'+notice['id']+'/check',data={'token':token})
        self.assertEqual(response.status_code,303)
        self.assertEqual(len(decision.call_args.args[1]),2)
        notices,links=w.overview(self.topic)
        self.assertEqual(notices[0]['check'],result)
        self.assertEqual(notices[0]['status'],'pending')
        self.assertEqual(next(s for s in links[0]['sides'] if s['lang']=='en')['baseline_text'],self.quotes['en'])

    def test_removed_or_ambiguous_passage_requires_review(self):
        self.edit('en',self.quotes['en']+'\n'+self.quotes['en'])
        notices,_=w.overview(self.topic)
        self.assertEqual(notices[0]['kind'],'link_needs_review')
        with self.assertRaises(ValueError):w.review(notices[0]['id'],'no_update','Cannot find exact passage')
        w.review(notices[0]['id'],'unlink','Duplicate location is ambiguous.')
        _,count=self.edit('en','Different content entirely.')
        self.assertEqual(count,0)

    def test_whitespace_and_html_escaping(self):
        _,count=self.edit('en',self.docs['en']['text'].replace('1000 residents','1000  residents'))
        self.assertEqual(count,0)
        html=str(w.diff_html('<script>old</script>','<script>new</script>'))
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)

    def test_csrf_and_confirmation_required(self):
        from app import app
        client=app.test_client()
        self.assertEqual(client.post('/watchlist/links',data={}).status_code,403)
        client.get('/watchlist')
        with client.session_transaction() as session:token=session['review_token']
        self.assertEqual(client.post('/watchlist/links',data={'token':token}).status_code,400)

class LocalTranslationTests(unittest.TestCase):
    def test_local_translation_and_cache_without_api(self):
        from local_translation import init,translate
        init()
        with patch('live_api.requests.post',side_effect=AssertionError('No API allowed')):
            for lang,text,number in [('fi','Vuonna 1888 koulut siirtyivät käyttämään kokonaan ruotsinkielistä opetusta.','1888'),
                                     ('sv','Tornedalingarna blev en nationell minoritet 1999.','1999')]:
                result=translate(text,lang)
                self.assertIn(number,result['text'])
                self.assertTrue(translate(text,lang)['cached'])

if __name__=='__main__':unittest.main(verbosity=2)
