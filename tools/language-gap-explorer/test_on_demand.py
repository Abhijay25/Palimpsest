"""Offline queue/worker boundary tests. No database, model or provider required."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import on_demand_jobs as jobs
import on_demand_bridge as bridge
import on_demand_worker as worker


def source(text='Actual frozen source', revision=123):
    return dict(lang='en', title='Winter War', page_id=12, revision_id=revision,
                parent_id=122, timestamp='2020-01-01T00:00:00Z',
                wikitext=text, sha256=hashlib.sha256(text.encode()).hexdigest())


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.p = dict(version=1, policy_version='fixture-v1', enabled=True, authorization='OFFLINE TEST ONLY',
            engines={kind: dict(enabled=True, topics=['Q134949'], authorization='OFFLINE FIXTURE ONLY',
                                max_provider_calls=2, allow_rescan=True,
                                configuration=dict(provider='gemini',model='fixture-model',reviewer_model='fixture-reviewer',
                                    triage_model='fixture-triage',prompt_version='fixture-prompt',policy_version='fixture-policy',max_output_tokens=100))
                     for kind in ('page','revision')})
        self.policy = self.folder / 'policy.json'
        self.write_policy()
        self.env = patch.dict(os.environ, NEOWIKI_ON_DEMAND_ROOT=str(self.folder/'queue'),NEOWIKI_ON_DEMAND_POLICY=str(self.policy))
        self.env.start();self.addCleanup(self.env.stop)
        jobs.init()

    def write_policy(self):
        self.policy.write_text(json.dumps(self.p), encoding='utf-8')

    def config(self, **changes):
        return dict(version='fixture',kind='page',topic='Q134949',implementation='fixture-code',
                    engine=self.p['engines']['page']['configuration'],authorization=jobs.digest(self.p),policy_version='fixture-v1',**changes)

    def plan(self, sources=None, config=None, scope='native-en'):
        return jobs.save_plan(scope,config or self.config(),sources or [source()])

    def enqueue(self, plan=None, previous=None):
        return jobs.enqueue((plan or self.plan())['id'],'native-en','Q134949',9,previous)

    def claim(self):
        return jobs.claim()

    def test_reads_do_not_create_directory_or_schema(self):
        path=self.folder/'absent'
        with patch.dict(os.environ,NEOWIKI_ON_DEMAND_ROOT=str(path)):
            with self.assertRaises(sqlite3.OperationalError):jobs.recent('native-en','Q134949')
            self.assertFalse(path.exists())

    def test_default_disabled_and_no_campaign_inheritance(self):
        with patch.dict(os.environ,NEOWIKI_ON_DEMAND_POLICY=''):
            self.assertFalse(jobs.permit(self.config())[0])
            self.assertFalse(bridge.describe('Q134949')['enabled'])
        self.p['engines']['page']['topics']=['Q2'];self.write_policy()
        with self.assertRaises(ValueError):self.enqueue()

    def test_concurrent_enqueue_is_idempotent_and_single_claim(self):
        plan=self.plan()
        with ThreadPoolExecutor(8) as pool:
            rows=list(pool.map(lambda _:self.enqueue(plan),range(16)))
        self.assertEqual(len({r['id'] for r in rows}),1)
        with ThreadPoolExecutor(4) as pool:
            claims=list(pool.map(lambda _:self.claim(),range(4)))
        self.assertEqual(sum(c is not None for c in claims),1)

    def test_job_scope_and_anonymous_write(self):
        item=self.enqueue()
        with self.assertRaises(LookupError):jobs.get(item['id'],'native-fi','Q134949')
        with self.assertRaises(LookupError):jobs.get(item['id'],'native-en','Q2')
        with self.assertRaises(ValueError):jobs.enqueue(self.plan()['id'],'native-en','Q134949',0)
        with self.assertRaises(ValueError):bridge.dispatch(dict(op='enqueue',wiki='native-en',query={}), 'Q134949')
        with self.assertRaises(LookupError):jobs.enqueue(self.plan(scope='native-fi')['id'],'native-fi','Q134949',7)

    def test_exact_source_parent_model_prompt_policy_identity(self):
        original=self.enqueue()
        modified=self.enqueue(self.plan([source('Changed text')]))
        self.assertNotEqual(original['id'],modified['id'])
        old_parent=source();old_parent.update(parent_wikitext='old',parent_sha256=hashlib.sha256(b'old').hexdigest())
        new_parent=dict(old_parent,parent_wikitext='different',parent_sha256=hashlib.sha256(b'different').hexdigest())
        self.assertNotEqual(self.plan([old_parent])['id'],self.plan([new_parent])['id'])
        for field in ('model','prompt_version','policy_version'):
            cfg=self.config();cfg['engine']=dict(cfg['engine'],**{field:'new-version'})
            self.assertNotEqual(self.plan(config=cfg)['id'],self.plan()['id'])

    def test_source_integrity_rejected(self):
        bad=source();bad['wikitext']='not matching'
        with self.assertRaises(ValueError):self.plan([bad])
        with patch('on_demand_bridge.fetch_source',return_value=source()):
            expected=dict(source(),sha256='0'*64)
            with self.assertRaises(LookupError):bridge.source_record('en',123,'Winter War',expected)

    def test_failed_unknown_partial_are_not_retried(self):
        original=self.enqueue()
        for state in ('failed','held_unknown','partial'):
            jobs.update(original['id'],state)
            self.assertEqual(self.enqueue()['status'],state)
            with self.assertRaises(ValueError):self.enqueue(previous=original['id'])
        self.assertIsNone(self.claim())

    def test_explicit_rescan_requires_success_and_deduplicates_generation(self):
        original=self.enqueue();jobs.update(original['id'],'completed',result={'findings':0,'partial':False})
        fresh=self.enqueue(previous=original['id'])
        self.assertNotEqual(original['id'],fresh['id'])
        self.assertEqual(fresh['id'],self.enqueue(previous=original['id'])['id'])
        self.assertEqual(self.enqueue()['status'],'completed')

    def test_revocation_blocks_enqueue_and_new_provider_calls(self):
        plan=self.plan();self.p['enabled']=False;self.write_policy()
        with self.assertRaises(ValueError):self.enqueue(plan)
        self.p['enabled']=True;self.write_policy();self.enqueue();job=self.claim()
        self.p['engines']['page']['enabled']=False;self.write_policy()
        with self.assertRaises(ValueError):jobs.reserve_attempt(job,{'input':'fixture'})

    def test_attempts_are_durable_keep_failure_reservations_and_raw_usage(self):
        self.enqueue();job=self.claim()
        aid,hit=jobs.reserve_attempt(job,{'input':'fixture-one'});self.assertIsNone(hit)
        jobs.finish_attempt(aid,error='TimeoutError')
        with self.assertRaises(RuntimeError):jobs.reserve_attempt(job,{'input':'fixture-one'})
        bid,_=jobs.reserve_attempt(job,{'input':'fixture-two'})
        raw={'usage_metadata':{'prompt_token_count':9},'raw':'preserved'}
        jobs.finish_attempt(bid,raw)
        self.assertEqual(jobs.reserve_attempt(job,{'input':'fixture-two'})[1],raw)
        with self.assertRaises(RuntimeError):jobs.reserve_attempt(job,{'input':'fixture-three'})
        self.assertEqual(worker.attempts(job)['calls'],2)
        self.assertEqual(worker.attempts(job)['failed_or_unknown'],1)

    def test_expired_preview_can_be_prepared_again(self):
        plan=self.plan()
        with jobs.database(True) as db:db.execute('UPDATE plan SET created=0')
        with self.assertRaises(LookupError):self.enqueue(plan)
        self.assertEqual(self.plan()['id'],plan['id'])
        self.assertEqual(self.enqueue(plan)['status'],'queued')

    def test_worker_crash_holds_uncertain_without_repeat(self):
        item=self.enqueue();self.claim();jobs.recover_interrupted()
        self.assertEqual(jobs.get(item['id'],'native-en','Q134949')['status'],'held_unknown')
        self.assertIsNone(self.claim())

    def test_raw_result_recovery_indexes_without_provider_even_after_revocation(self):
        item=self.enqueue();job=self.claim()
        worker.archive(job,{'status':'ok','flags':[]})
        jobs.recover_interrupted()
        self.assertEqual(jobs.get(item['id'],'native-en','Q134949')['status'],'awaiting_index')
        self.p['enabled']=False;self.write_policy();self.claim()
        with patch('on_demand_worker.disk'),patch('on_demand_worker.detector',new_callable=AsyncMock) as detector,patch('on_demand_worker.index_result',return_value={'findings':0,'partial':False}) as index:
            worker.run_one(item['id'])
            detector.assert_not_called();index.assert_called_once()
        complete=jobs.get(item['id'],'native-en','Q134949')
        self.assertEqual(complete['status'],'completed');self.assertEqual(complete['result']['findings'],0)

    def test_worker_offline_success_empty_and_failure_keep_prior_result(self):
        item=self.enqueue();self.claim()
        with patch('on_demand_worker.disk'),patch('on_demand_worker.compatible_scan',return_value=None),patch('on_demand_bridge.implementation_identity',return_value='fixture-code'),patch('on_demand_worker.detector',new_callable=AsyncMock,return_value={'status':'ok','flags':[]}),patch('on_demand_worker.index_result',return_value={'findings':0,'partial':False}):
            worker.run_one(item['id'])
        self.assertEqual(jobs.get(item['id'],'native-en','Q134949')['status'],'completed')
        rescan=self.enqueue(previous=item['id']);self.claim()
        with patch('on_demand_worker.disk'),patch('on_demand_worker.compatible_scan',return_value=None),patch('on_demand_bridge.implementation_identity',return_value='fixture-code'),patch('on_demand_worker.detector',new_callable=AsyncMock,side_effect=TimeoutError):
            worker.run_one(rescan['id'])
        self.assertEqual(jobs.get(rescan['id'],'native-en','Q134949')['status'],'failed')
        self.assertEqual(jobs.get(item['id'],'native-en','Q134949')['result']['findings'],0)

    def test_policy_refuses_credentials_in_public_configuration(self):
        self.p['engines']['page']['configuration']['GEMINI_API_KEY']='fixture-secret';self.write_policy()
        with self.assertRaises(ValueError):jobs.policy()


if __name__=='__main__':unittest.main()
