"""Opt-in detector adapter fixtures. SDK responses are mocked; no network calls.

Set NEOWIKI_TEST_DETECTOR_ADAPTER=1 only in an environment with detector deps.
The VPS validation runs this inside its installed image with --network none.
"""
import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
import on_demand_jobs as jobs
import on_demand_worker as worker
import test_on_demand as fixtures


@unittest.skipUnless(os.environ.get('NEOWIKI_TEST_DETECTOR_ADAPTER')=='1','Requires installed detector dependencies; all SDK calls remain fixtures.')
class DetectorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.QueueTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def job(self, text='An offline synthetic source with no factual assertions.'):
        from palimpsest import api
        f=self.fixture
        f.p['engines']['page']['configuration']['prompt_version']=api.PROMPT_VERSION;f.write_policy()
        f.enqueue(f.plan([fixtures.source(text)]))
        return f.claim()

    def execute(self, job, network, adjudicate):
        from google.genai.models import AsyncModels
        import palimpsest.backends.gemini as backend
        from palimpsest import api
        old_client=backend.Client
        old_generate=backend._GeminiCaller.generate
        original_cwd=Path.cwd()
        with patch.dict(os.environ,GEMINI_API_KEY='OFFLINE-FIXTURE-NOT-A-REAL-KEY'),patch.object(AsyncModels,'generate_content',network),patch.object(api,'get_page_consistency_judge',return_value=object()),patch.object(api,'adjudicate_page',adjudicate),patch('on_demand_worker.disk'):
            try:return asyncio.run(worker.detector(job))
            finally:
                backend.Client=old_client;backend._GeminiCaller.generate=old_generate
                os.chdir(original_cwd)

    def test_real_page_adapter_archives_usage_and_reuses_exact_sdk_attempt(self):
        from google.genai import types
        from google.genai.models import AsyncModels
        job=self.job()
        response=types.GenerateContentResponse.model_validate(dict(candidates=[dict(content=dict(parts=[dict(text='offline fixture')],role='model'))],usage_metadata=dict(prompt_token_count=5,candidates_token_count=1)))
        sdk=AsyncMock(return_value=response)
        async def adjudicate(text,judge):
            for _ in range(2):
                await AsyncModels.generate_content(object(),model=job['config']['engine']['model'],contents='Exact offline fixture request',config=types.GenerateContentConfig())
            return [],[]
        result=self.execute(job,sdk,adjudicate)
        sdk.assert_awaited_once()
        self.assertEqual(result['status'],'ok');self.assertEqual(result['flags'],[])
        self.assertEqual(result['provider_usage']['calls'],1)
        self.assertEqual(result['provider_usage']['usage'][0]['prompt_token_count'],5)
        self.assertEqual(result['source_sha256'],job['sources'][0]['sha256'])

    def test_sdk_timeout_reservation_blocks_a_second_network_attempt(self):
        from google.genai import types
        from google.genai.models import AsyncModels
        job=self.job('Another exact offline source.');sdk=AsyncMock(side_effect=TimeoutError)
        async def adjudicate(text,judge):
            kwargs=dict(model=job['config']['engine']['model'],contents='Exact failed fixture',config=types.GenerateContentConfig())
            try:await AsyncModels.generate_content(object(),**kwargs)
            except TimeoutError:
                # Simulate an outer retry. The retained exact reservation blocks
                # it before the mocked network transport can be invoked again.
                await AsyncModels.generate_content(object(),**kwargs)
            return [],[]
        with self.assertRaises(RuntimeError):self.execute(job,sdk,adjudicate)
        sdk.assert_awaited_once()
        self.assertEqual(worker.attempts(job)['failed_or_unknown'],1)


if __name__=='__main__':unittest.main()
