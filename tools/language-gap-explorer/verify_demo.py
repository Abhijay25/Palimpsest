"""Real model + MariaDB + Flask integration checks. Run after prepare.py."""
import unittest
from unittest.mock import patch
from core import connect, compare, split_passages
from prepare import embedding_model
from app import app
import requests

class DemoChecks(unittest.TestCase):
    def test_mock_review_preserves_real_quotes(self):
        from mock_review import mock_review
        with connect() as db,db.cursor() as c:
            c.execute('SELECT * FROM article WHERE wikidata_id=%s',('Q2606233',))
            articles={a['lang']:a for a in c.fetchall()}
        findings=mock_review('Q2606233',articles)
        self.assertEqual(len(findings),4)
        for finding in findings:
            self.assertEqual(finding['mode'],'mock')
            for e in finding['evidence']:
                self.assertEqual(e['quote'],articles[e['lang']]['text'][e['start']:e['end']])
        self.assertEqual(mock_review('Q33',{}),[])
    def test_article_markdown_safety_and_navigation(self):
        from article_render import render_article
        html,contents=render_article('# Example\n\n<script>alert(1)</script>\n\n## History\n\n[Bad](javascript:alert(1))','en','Example')
        self.assertNotIn('<script>',html)
        self.assertNotIn('href="javascript:',html)
        self.assertEqual(contents[0]['title'],'History')
        client=app.test_client()
        self.assertIn('/wiki/',client.get('/').location)
        article=client.get('/wiki/Q2606233?lang=en')
        self.assertEqual(article.status_code,200)
        self.assertIn(b'/langcompare/Q2606233?source=en',article.data)
        self.assertEqual(client.get('/wiki/Q2606233?lang=xx').status_code,400)
    @classmethod
    def setUpClass(cls):
        cls.model=embedding_model()

    def test_split_preserves_long_section_and_source(self):
        text='This is a long section. '*1000+'FINAL SENTENCE.'
        parts=list(split_passages(text,self.model.model.tokenizer))
        self.assertGreater(len(parts),3)
        self.assertIn('FINAL SENTENCE.',parts[-1][1])
        for _,part in parts:
            self.assertIn(part,text)
            self.assertLessEqual(len(self.model.model.tokenizer.encode(part).ids),402)

    def test_semantic_ranking_in_mariadb(self):
        texts=['query: Finland became independent in 1917.',
               'query: Suomi itsenäistyi vuonna 1917.',
               'query: This recipe requires flour and eggs.']
        vectors=[str(v.tolist()) for v in self.model.embed(texts)]
        with connect() as db, db.cursor() as c:
            scores=[]
            for v in vectors:
                c.execute('SELECT 1-VEC_DISTANCE_COSINE(VEC_FromText(%s),VEC_FromText(%s)) AS score',(vectors[0],v))
                scores.append(float(c.fetchone()['score']))
        self.assertGreater(scores[0],.999)
        self.assertGreater(scores[1],scores[2])
        print('Actual cosine similarities: identical / Finnish counterpart / unrelated:',scores)

    def test_both_directions_and_cached_pages(self):
        with connect() as db, db.cursor() as c:
            c.execute('SELECT COUNT(*) AS n FROM passage'); before=c.fetchone()['n']
            c.execute('SELECT DISTINCT a.wikidata_id FROM article a JOIN passage p ON p.lang=a.lang AND p.page_id=a.page_id')
            topics=c.fetchall()
            self.assertEqual(len(topics),5)
            client=app.test_client()
            for row in topics:
                topic=row['wikidata_id']
                for source,target in [('fi','en'),('en','fi'),('sv','en')]:
                    matches=compare(c,topic,source,target)
                    self.assertTrue(matches)
                    self.assertEqual(matches,sorted(matches,key=lambda r:r['similarity']))
                    self.assertEqual(client.get(f'/topic/{topic}?source={source}&target={target}').status_code,200)
            c.execute('SELECT COUNT(*) AS n FROM passage'); self.assertEqual(before,c.fetchone()['n'])

    def test_invalid_and_missing_topics(self):
        client=app.test_client()
        self.assertEqual(client.get('/topic/invalid').status_code,404)
        self.assertEqual(client.get('/topic/Q999999999999').status_code,404)
        self.assertEqual(client.get('/topic/Q33?source=en&target=en').status_code,400)

    def test_live_failure_is_unknown(self):
        # A topic with no cached verification, avoiding mutation of existing cache.
        with connect() as db, db.cursor() as c:
            c.execute('SELECT wikidata_id FROM article WHERE wikidata_id IS NOT NULL AND wikidata_id NOT IN (SELECT wikidata_id FROM verification) LIMIT 1')
            topic=c.fetchone()['wikidata_id']
        with patch('app.requests.get',side_effect=requests.Timeout):
            response=app.test_client().post(f'/topic/{topic}/verify')
        self.assertEqual(response.status_code,502)
        self.assertIn('unknown',response.json['error'])

if __name__=='__main__': unittest.main(verbosity=2)
