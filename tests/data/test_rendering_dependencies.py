import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from scripts.acquire_wikidata import capture,references
from scripts.prepare_wiki_rendering import prepare,verify


class WikidataCaptureTests(unittest.TestCase):
    def test_explicit_one_hop_is_bounded_cached_and_integrity_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls=[]
            def api(url,**kwargs):
                from urllib.parse import parse_qs,urlsplit
                ids=parse_qs(urlsplit(url).query)['ids'][0].split('|');calls.extend(ids)
                return {'entities':{identity:dict(id=identity,lastrevid=100+len(calls),type='property' if identity.startswith('P') else 'item',claims={'P31':[{'mainsnak':{'property':'P31','datavalue':{'value':{'id':'Q5'}}}}]} if identity=='Q1' else {}) for identity in ids}}
            result=capture(root,['Q1'],limit=3,linked=True,api=api)
            self.assertTrue(result['complete']);self.assertEqual(set(calls),{'Q1','P31','Q5'})
            capture(root,['Q1'],limit=3,linked=True,api=lambda *a,**k:self.fail('Cached reads must not acquire data'))
            (root/'Q1.json').write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):capture(root,['Q1'],api=api)

    def test_reference_collection_does_not_treat_label_text_as_entity_identity(self):
        entity={'id':'Q1','labels':{'en':{'value':'Q999'}},'claims':{'P31':[{'mainsnak':{'property':'P31','datavalue':{'value':{'id':'Q5'}}}}]}}
        self.assertEqual(references(entity),{'P31','Q5'})

    def test_entity_limit_remains_partial_and_source_failures_preserve_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def api(*a,**k):return {'entities':{'Q1':{'id':'Q1','lastrevid':1,'claims':{'P31':[]}}}}
            result=capture(root,['Q1'],limit=1,linked=True,api=api)
            self.assertFalse(result['complete']);self.assertEqual(result['pending'],['P31'])
            saved=(root/'Q1.json').read_bytes()
            with self.assertRaises(OSError):capture(root,['Q1'],limit=2,linked=True,api=lambda *a,**k:(_ for _ in ()).throw(OSError('source unavailable')))
            self.assertEqual((root/'Q1.json').read_bytes(),saved)
            self.assertFalse(json.loads((root/'manifest.json').read_text(encoding='utf-8'))['complete'])


class RenderingPackageTests(unittest.TestCase):
    def package(self,root,unsafe=False):
        package=root/'package.tar.gz'
        with tarfile.open(package,'w:gz') as archive:
            for name,data in [('Wikibase/gitinfo.json',json.dumps({'headSHA1':'exact-commit'})),('Wikibase/vendor/autoload.php','<?php // fixture')]:
                body=data.encode();member=tarfile.TarInfo(name);member.size=len(body);archive.addfile(member,io.BytesIO(body))
            if unsafe:
                member=tarfile.TarInfo('Wikibase/../../outside');member.size=1;archive.addfile(member,io.BytesIO(b'x'))
        return package,{'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'commit':'exact-commit'}

    def test_pinned_package_and_modified_stage_are_checked_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'.local/wb';package,pin=self.package(root)
            with patch('scripts.prepare_wiki_rendering.ROOT',root):
                prepare(package,output,pin);verify(package,output,pin)
                file=output/'vendor/autoload.php';file.write_text('local change',encoding='utf-8')
                with self.assertRaises(ValueError):prepare(package,output,pin,check=True)
                self.assertEqual(file.read_text(encoding='utf-8'),'local change')

    def test_escaping_package_and_existing_unregistered_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'.local/wb';package,pin=self.package(root,unsafe=True)
            with patch('scripts.prepare_wiki_rendering.ROOT',root):
                with self.assertRaises(ValueError):prepare(package,output,pin)
                self.assertFalse((root/'outside').exists())
            output.mkdir(parents=True,exist_ok=True);file=output/'keep.txt';file.write_text('Existing work',encoding='utf-8')
            package,pin=self.package(root)
            with patch('scripts.prepare_wiki_rendering.ROOT',root):
                with self.assertRaises(ValueError):prepare(package,output,pin)
                self.assertEqual(file.read_text(encoding='utf-8'),'Existing work')

if __name__=='__main__':unittest.main()
