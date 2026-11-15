import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock

import issue_context as context
from issue_evidence import evidence_view

class IssueContextTests(unittest.TestCase):
    def row(self):
        return dict(id='issue',observation='observation',mode='language',kind='coverage',title='Which information is included?',label='Missing context',stamp='2025-01-01',
            evidence=dict(evidence=[dict(lang='en',revision=1,stamp='2024-01-01',quote='The border moved west. Fortifications were demolished.',section='Peace treaty'),
                dict(lang='sv',revision=2,stamp='2024-01-01',quote='Gränsen flyttades västerut.',section='Bakgrund')]))

    def test_reads_describe_sources_without_translation_or_provider_calls(self):
        row=self.row();original=copy.deepcopy(row)
        with tempfile.TemporaryDirectory() as folder,patch('issue_context.ROOT',Path(folder)),patch('issue_evidence.connect',side_effect=RuntimeError('cache unavailable')),patch('local_translation.cached_translation',return_value=None),patch('local_translation.translate',side_effect=AssertionError('No inference while browsing')):
            view=evidence_view(row,'en')
        self.assertEqual(row,original)
        self.assertIn('EN: “The border moved west.”',view['flags'][0]['reason'])
        self.assertIn('SV: “Gränsen flyttades västerut.”',view['flags'][0]['reason'])
        self.assertEqual(view['flags'][0]['comment_group'],view['flags'][1]['comment_group'])
        self.assertEqual(len(view['translation_sources']),1)
        self.assertFalse(view['translation_sources'][0]['cached'])

    def test_context_bound_prepared_explanation_and_changed_revision(self):
        row=self.row();sources=row['evidence']['evidence']
        with tempfile.TemporaryDirectory() as folder,patch('issue_context.ROOT',Path(folder)):
            target=context.explanation_path(row['kind'],sources);target.parent.mkdir(parents=True)
            target.write_text(json.dumps(dict(version=context.VERSION,scope_key=context.scope_key(row['kind'],sources),summary='English lists fortification removal; the selected Swedish sentence only states the border shift.',title='Border shift and fortifications')),encoding='utf-8')
            self.assertTrue(context.description(row,sources)['prepared'])
            sources[0]['revision']=99
            self.assertFalse(context.description(row,sources)['prepared'])

    def test_explicit_translation_is_bound_to_exact_observation(self):
        row=self.row();source=row['evidence']['evidence'][1]
        with patch('local_translation.translate',return_value=dict(text='The border moved west.',cached=False,model='local-test')) as translate:
            with self.assertRaises(LookupError):context.translate_source(row,'not-this-source')
            translate.assert_not_called()
            result=context.translate_source(row,context.source_key(source))
            translate.assert_called_once_with(source['quote'],'sv')
            self.assertEqual(result['observation'],'observation')

    def test_cached_translation_does_not_load_a_model(self):
        db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={'translated':'Cached English.'}
        with patch('local_translation.connect',return_value=db),patch('local_translation.load_model',side_effect=AssertionError('Cache read must not load model')):
            from local_translation import cached_translation
            self.assertEqual(cached_translation('Original','sv')['text'],'Cached English.')

    def test_conflicting_classifier_and_reference_evidence_are_explicit(self):
        row=self.row();row['kind']='contradiction';row['evidence']['scores']={'compatible':{'probability':1.}}
        with tempfile.TemporaryDirectory() as folder,patch('issue_context.ROOT',Path(folder)):
            self.assertIn('signals conflict',context.description(row,row['evidence']['evidence'])['reason'])
            row['evidence']['evidence'][1].update(lang='fi',section='Aiheesta muualla')
            self.assertIn('reference/link section',context.description(row,row['evidence']['evidence'])['reason'])

    def test_each_paragraph_has_its_own_inline_translation_and_exact_source(self):
        row=self.row();source=row['evidence']['evidence'][1];source['quote']='Första stycket.\n\nAndra stycket.'
        parts=context.paragraphs(source)
        self.assertEqual([p['quote'] for p in parts],['Första stycket.','Andra stycket.'])
        self.assertNotEqual(context.source_key(parts[0]),context.source_key(parts[1]))
        with patch('local_translation.cached_translation',return_value=None),patch('issue_evidence.connect',side_effect=RuntimeError('no cache')):
            view=evidence_view(row,'en')
        self.assertEqual(str(view['diff_html']).count('issue-translation-slot'),2)
        self.assertEqual(len(view['translation_sources']),2)
        with patch('local_translation.translate',return_value={'text':'Second paragraph.','cached':False}) as translator:
            context.translate_source(row,context.source_key(parts[1]))
            translator.assert_called_once_with('Andra stycket.','sv')

if __name__=='__main__':unittest.main()
