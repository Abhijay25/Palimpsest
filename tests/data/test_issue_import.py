import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
from scripts.import_issue_sources import cached_support_resolver,exact_records,source_namespaces


class ExactImportTests(unittest.TestCase):
    def test_current_batch_never_claims_historical_cutoff_and_preserves_internal_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);progress=root/'progress.json'
            progress.write_text(json.dumps(dict(pending=['Module:Example/Data','Module:Example/data'])))
            calls=[]
            def api(url,**kwargs):
                query=parse_qs(urlsplit(url).query);calls.append(query)
                self.assertNotIn('rvstart',query);self.assertNotIn('rvlimit',query)
                return {'query':{'pages':[dict(pageid=n,title=t,revisions=[dict(revid=100+n,timestamp='2026-01-01T00:00:00Z',slots={'main':{'content':'exact '+t,'contentmodel':'Scribunto'}})]) for n,t in enumerate(query['titles'][0].split('|'),1)]}}
            resolve=cached_support_resolver('en',progress,root/'cache',api=api)
            with patch('scripts.import_issue_sources.time.sleep'):
                first=resolve('Module:Example/Data','2026-02-01T00:00:00Z')
                second=resolve('Module:Example/data','2026-02-01T00:00:00Z')
            self.assertNotEqual(first['source_revision_id'],second['source_revision_id'])
            self.assertEqual(len(calls),1)
            self.assertEqual(first['timestamp'],'2026-01-01T00:00:00Z')

    def test_explicit_missing_retry_rechecks_negative_source_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);progress=root/'progress.json'
            with patch('scripts.import_issue_sources.time.sleep'),patch('scripts.import_issue_sources.fetch_json'):
                missing=cached_support_resolver('sv',progress,root/'cache',api=lambda *a,**k:{'query':{'pages':[]}})
                self.assertIsNone(missing('Mall:Example','2026-02-01T00:00:00Z'))
                def api(*a,**k):
                    return {'query':{'pages':[dict(pageid=1,title='Mall:Example',revisions=[dict(revid=2,timestamp='2026-01-01T00:00:00Z',slots={'main':{'content':'Actual source','contentmodel':'wikitext'}})])]}}
                resumed=cached_support_resolver('sv',progress,root/'cache',api=api,retry_titles=['Mall:Example'])
                self.assertEqual(resumed('Mall:Example','2026-02-01T00:00:00Z')['source_revision_id'],2)

    def test_namespace_configuration_uses_source_ids_and_localized_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'cache';target=root/'namespaces.json';calls=[]
            def api(url,**kwargs):
                calls.append(url)
                return {'query':{'namespaces':{'0':{'id':0,'name':'','canonical':''},'100':{'id':100,'name':'Portaali','canonical':'Portal'},'101':{'id':101,'name':'Keskustelu portaalista','canonical':'Portal talk'}}}}
            records=source_namespaces('fi',['Portal'],cache,target,api=api)
            self.assertEqual(records,[{'id':100,'name':'Portaali'},{'id':101,'name':'Keskustelu_portaalista'}])
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['source_wiki'],'fiwiki')
            source_namespaces('fi',['Portal'],cache,target,api=api)
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):source_namespaces('fi',['Missing'],cache,target,api=api)

    def test_wrong_source_page_fails_before_import(self):
        article=dict(language='en',source_wiki='enwiki',source_page_id=12,title='Real article',anchor_revision_id=22)
        with tempfile.TemporaryDirectory() as directory,patch('scripts.import_issue_sources.fetch_json',return_value={'query':{'pages':[dict(pageid=99,title='Other',revisions=[])]}}):
            with self.assertRaises(ValueError):exact_records(article,[22],Path(directory))

if __name__=='__main__':unittest.main()
