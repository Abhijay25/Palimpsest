"""Article isolation, truthful calendar coverage and queue-selection checks."""
from dataclasses import FrozenInstanceError
import copy
import json
import unittest
from unittest.mock import patch,MagicMock

import article_pipeline as article
import paired_history as paired


def context(topic='Q1',mode='history'):
    return article.ArticleContext(topic,'Example',(
        article.EditionAnchor('en',1,100,'Example','2020-03-15T12:00:00Z'),
        article.EditionAnchor('fi',2,200,'Esimerkki','2020-03-20T00:00:00Z')),mode)


def manifest():
    return dict(history={
        'en':[dict(revid=1,timestamp='2019-12-15T00:00:00Z'),dict(revid=2,timestamp='2020-02-10T00:00:00Z')],
        'fi':[dict(revid=3,timestamp='2019-12-16T00:00:00Z'),dict(revid=4,timestamp='2020-03-01T00:00:00Z')]})


class ArticlePipelineTests(unittest.TestCase):
    def test_context_is_immutable_and_has_normalized_languages(self):
        ctx=context()
        with self.assertRaises(FrozenInstanceError):ctx.topic='Q2'
        self.assertEqual(ctx.languages,('en','fi'))
        self.assertEqual(ctx.cutoff,'2020-03-15T12:00:00Z')

    def test_run_identity_is_article_and_anchor_scoped(self):
        a=context();b=context('Q2')
        config_a=article.run_configuration(a,article.checkpoint_schedule(a,manifest()))
        config_b=article.run_configuration(b,article.checkpoint_schedule(b,manifest()))
        self.assertNotEqual(article.storage.digest(config_a),article.storage.digest(config_b))
        self.assertIn('anchors',config_a);self.assertIn('revision_tuples',config_a)
        from pipeline import PASSAGE_VERSION
        self.assertEqual(config_a['passage_policy'],PASSAGE_VERSION)
        legacy=dict(config_a);legacy.pop('passage_policy')
        self.assertNotEqual(article.storage.digest(config_a),article.storage.digest(legacy))

    def test_monthly_checkpoints_and_real_recent_days(self):
        points=article.checkpoint_schedule(context(),manifest());by_stamp={p['stamp']:p for p in points}
        self.assertIn('2020-01-31T23:59:59Z',by_stamp)
        self.assertIn('2020-02-29T23:59:59Z',by_stamp)
        self.assertIn('2020-02-10T00:00:00Z',by_stamp)
        self.assertIn(context().cutoff,by_stamp)
        for p in points:
            self.assertTrue(all(r['timestamp']<=p['stamp'] for r in p['revisions'].values()))

    def test_missing_historical_editions_are_explicit_gaps(self):
        data=manifest();data['fi']=[]
        data['history']['fi']=[dict(revid=4,timestamp='2020-03-01T00:00:00Z')]
        points=article.checkpoint_schedule(context(),data)
        january=next(p for p in points if p['stamp']=='2020-01-31T23:59:59Z')
        self.assertEqual(january['state'],'unknown');self.assertEqual(january['missing'],['fi'])

    def test_snapshot_has_one_shared_asof(self):
        points=article.checkpoint_schedule(context(mode='snapshot'),manifest())
        self.assertEqual(len(points),1);self.assertEqual(points[0]['stamp'],context().cutoff)
        self.assertEqual(points[0]['revisions']['en']['revid'],2)

    def test_unchanged_tuples_keep_each_calendar_checkpoint(self):
        points=article.checkpoint_schedule(context(),manifest())
        march=next(p for p in points if p['stamp']==context().cutoff)
        change=next(p for p in points if p['stamp']=='2020-03-01T00:00:00Z')
        self.assertEqual(march['revision_tuple'],change['revision_tuple'])
        self.assertNotEqual(march['stamp'],change['stamp'])

    def test_pilot_is_deterministic_mixed_and_bounded(self):
        rows=[dict(topic='Q'+str(i),languages=['en,fi','en,sv','fi,sv'][i%3],prose_length=i*100,title=str(i)) for i in range(1,60)]
        rows.append(dict(topic='Q134949',languages='en,fi,sv',prose_length=10000,title='Winter War'))
        a=article.pilot_articles(rows);b=article.pilot_articles(list(reversed(rows)))
        self.assertEqual(a,b);self.assertEqual(len(a),10);self.assertEqual(a[0]['topic'],'Q134949')
        self.assertGreater(len({r['languages'] for r in a}),1)

    def test_legacy_globals_never_change(self):
        old=(paired.TOPIC,paired.WORKERS,article.storage.TOPIC,article.storage.CACHE)
        article.checkpoint_schedule(context('Q2'),manifest())
        self.assertEqual(old,(paired.TOPIC,paired.WORKERS,article.storage.TOPIC,article.storage.CACHE))

    def test_grouping_sql_enforces_article_scope(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect=[[],[],[],[]]
        cursor.fetchone.return_value={'embedding':b'x'}
        pair=dict(id='p',a=dict(lang='en',section='A',quote='x'),b=dict(lang='fi',section='B',quote='y'))
        with patch('article_pipeline.connect',return_value=db),patch('paired_history.feature',return_value=b'vector'):
            result=article._assign_topics(context(),{'p':pair},{'p':dict(kind='coverage',question='cause')})
        self.assertIn('p',result)
        queries=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any('article_feature_scope' in q and 's.article=%s' in q for q in queries))
        self.assertTrue(any('article_semantic_topic' in q and 'article=%s' in q for q in queries))
        self.assertFalse(any('SELECT * FROM paired_topic' in q for q in queries))

    def test_v2_summary_preserves_unknown_gap_even_when_ready(self):
        data=dict(topic=dict(id='Q1',languages=['en','fi']),run='a'*64,version=article.VERSION,rows=[],
                  progress=dict(stage='ready',completed_checkpoints=1),observations=[dict(stamp='2020-01-31T23:59:59Z',state='unknown')])
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[dict(summary=json.dumps(data),configuration=json.dumps(dict(window=['2020-01-31T23:59:59Z'])))]
        with patch('paired_history.connect',return_value=db):result=paired.summary('Q1',['en','fi'])
        self.assertEqual(result['observations'][0]['state'],'unknown')

    def test_resume_skips_an_active_job(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value=[dict(id='a'*64)];cursor.fetchone.return_value=dict(locked=0)
        with patch('article_pipeline.init'),patch('article_pipeline.connect',return_value=db):changed=article.resume_queue('Q1')
        self.assertEqual(changed,0)
        self.assertFalse(any('UPDATE article_preparation_queue' in call.args[0] for call in cursor.execute.call_args_list))

    def test_duplicate_claim_never_starts_another_preparation(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value;cursor.fetchone.return_value=dict(locked=0)
        with patch('article_pipeline.connect',return_value=db),patch('article_pipeline._run_job_locked') as prepare:
            result=article._run_job(dict(id='a'*64))
        self.assertEqual(result['status'],'running_elsewhere');prepare.assert_not_called()

    def test_naming_stages_only_new_groups_or_final(self):
        result=dict(topic=dict(id='Q1',languages=['en','fi']),run='a'*64,rows=[dict(id='b')]);progress={}
        with patch('question_titles.stage',return_value=dict(pending_batches=1)) as stage:
            article.stage_names(result,progress);article.stage_names(result,progress)
            self.assertEqual(stage.call_count,1)
            article.stage_names(result,progress,final=True)
            self.assertEqual(stage.call_count,2)
        self.assertTrue(progress['naming_pending']);self.assertEqual(progress['naming_staged_groups'],1)

    def test_naming_stage_failure_does_not_fail_assessment(self):
        result=dict(topic=dict(id='Q1',languages=['en','fi']),run='a'*64,rows=[dict(id='b')]);progress={}
        with patch('question_titles.stage',side_effect=RuntimeError('private detail')):article.stage_names(result,progress)
        self.assertTrue(progress['naming_pending']);self.assertEqual(progress['naming_error'],'RuntimeError')

    def test_disk_guard_is_not_lowered(self):
        with patch('article_pipeline.shutil.disk_usage',return_value=MagicMock(free=511*1024*1024)):
            with self.assertRaises(article.DiskGuardError):article.ensure_disk_space()

    def test_disk_pause_stops_claiming_more_jobs(self):
        with patch('article_pipeline.init'),patch('article_pipeline._claim',return_value=dict(id='a')) as claim,patch('article_pipeline._run_job',return_value=dict(status='paused_disk')),patch('builtins.print'):
            result=article.work(workers=1)
        self.assertEqual(result[0]['status'],'paused_disk');self.assertEqual(claim.call_count,1)

    def test_showcase_uses_real_titles_and_latest_distinct_count(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        data=dict(asOf='2025-01-01T00:00:00Z',observations=[dict(stamp='2025-01-01T00:00:00Z')],rows=[
            dict(id='g',phases=[dict(start='2025-01-01T00:00:00Z'),dict(start='2025-01-01T00:00:00Z')]),
            dict(id='old',phases=[dict(start='2020-01-01T00:00:00Z')])])
        cursor.fetchall.side_effect=[[
            dict(topic='Q134949',lang='fi',title='Talvisota'),dict(topic='Q134949',lang='en',title='Dataset title'),dict(topic='Q134949',lang='sv',title='Vinterkriget')],
            [dict(topic='Q134949',id='run',status='ready',summary=json.dumps(data))],[]]
        with patch('article_pipeline.connect',return_value=db):rows=article.showcase_articles()
        self.assertEqual(rows[0]['title'],'Dataset title');self.assertEqual(rows[0]['count'],1);self.assertEqual(rows[0]['all_time_count'],2)
        self.assertTrue(rows[0]['featured']);self.assertEqual(rows[0]['status'],'ready')

    def test_failed_batch_remains_unassessed_in_partial_mode(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
        pairs={'a':dict(id='a',similarity=.9),'b':dict(id='b',similarity=.8)};on_error=MagicMock()
        with patch('paired_history.connect',return_value=db),patch('paired_history.verdict_batch',side_effect=RuntimeError('provider unavailable')):
            result=paired.assess(pairs,workers=1,allow_partial=True,on_error=on_error)
        self.assertEqual({v['kind'] for v in result.values()},{'unassessed'});on_error.assert_called_once()

    def test_legacy_failed_batch_still_raises(self):
        db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
        with patch('paired_history.connect',return_value=db),patch('paired_history.verdict_batch',side_effect=RuntimeError('provider unavailable')):
            with self.assertRaises(RuntimeError):paired.assess({'a':dict(id='a',similarity=.9)},workers=1)

    def test_unknown_group_check_defers_possible_duplicate(self):
        db=MagicMock();db.__enter__.return_value=db;cursor=db.cursor.return_value.__enter__.return_value
        near=dict(id='known',payload=json.dumps(dict(a='source',b='counterpart')))
        cursor.fetchall.side_effect=[[],[dict(id='group',representative='known')],[near],[near]]
        cursor.fetchone.side_effect=[dict(embedding=b'x'),dict(probability=None)]
        pair=dict(id='a',a=dict(lang='en',section='A',quote='x'),b=dict(lang='fi',section='B',quote='y'))
        with patch('article_pipeline.connect',return_value=db),patch('paired_history.feature',return_value=b'vector'),patch('paired_history.group_check_batch') as assess:
            result=article._assign_topics(context(),{'a':pair},{'a':dict(kind='coverage',question='cause')})
        self.assertEqual(result,{});assess.assert_not_called()
        self.assertFalse(any('INSERT IGNORE INTO article_semantic_topic' in c.args[0] for c in cursor.execute.call_args_list))

    def test_scoped_group_refusal_is_unknown_not_negative(self):
        db=MagicMock();db.__enter__.return_value=db
        with patch('paired_history.connect',return_value=db),patch('paired_history.decisions',return_value={'same_0':dict(type='refusal')}):
            result=paired.group_check_batch([('id',{}, {})],namespace='article-scope')
        self.assertIsNone(result['id'])


if __name__=='__main__':unittest.main()
