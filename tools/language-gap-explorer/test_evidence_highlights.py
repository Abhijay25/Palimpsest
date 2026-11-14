"""Exact localization and read-only highlight-cache behavior; no provider calls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import MagicMock,patch

import evidence_highlights as highlights

TOPIC='Q134949'
GROUP='a'*64


def occurrence(kind='framing'):
    return dict(id='b'*64,kind=kind,evidence=[
        dict(lang='en',quote='The account emphasizes negotiations. It also lists dates.',revision=1,stamp='2025-01-01T00:00:00Z'),
        dict(lang='fi',quote='Kuvaus painottaa sotilaallisia tavoitteita. Päivät mainitaan myös.',revision=2,stamp='2025-01-02T00:00:00Z')])


def packet():return highlights.make_packet(dict(topic=TOPIC,group=GROUP,occurrence=occurrence()))


def database(row=None):
    db=MagicMock();db.__enter__.return_value=db;db.cursor.return_value.__enter__.return_value.fetchone.return_value=row;return db


class HighlightTests(unittest.TestCase):
    def test_unicode_sentence_offsets_never_rewrite_source(self):
        text='  Mäkelä sanoi: “Ei vielä.”\n\nÅland är svenskspråkigt!  Loppu'
        spans=highlights.sentence_spans(text)
        self.assertEqual(len(spans),3)
        self.assertTrue(all(text[s['start']:s['end']]==s['text'] for s in spans))
        covered={i for s in spans for i in range(s['start'],s['end'])}
        self.assertTrue(all(c.isspace() or i in covered for i,c in enumerate(text)))

    def test_abbreviations_and_decimals_keep_exact_offsets(self):
        text='Dr. Mäkelä measured 3.5 units. Another sentence.'
        spans=highlights.sentence_spans(text)
        self.assertEqual(len(spans),2);self.assertTrue(spans[0]['text'].startswith('Dr.'))

    def test_identity_ignores_dates_revision_and_order(self):
        a=occurrence();b=deepcopy(a);b['evidence'].reverse()
        for e in b['evidence']:e['revision']=999;e['stamp']='2020-01-01'
        self.assertEqual(highlights.identity(TOPIC,GROUP,a),highlights.identity(TOPIC,GROUP,b))

    def test_identity_separates_group_category_and_exact_text(self):
        a=occurrence();base=highlights.identity(TOPIC,GROUP,a)
        self.assertNotEqual(base,highlights.identity(TOPIC,'c'*64,a))
        self.assertNotEqual(base,highlights.identity(TOPIC,GROUP,occurrence('contradiction')))
        a['evidence'][0]['quote']+=' ';self.assertNotEqual(base,highlights.identity(TOPIC,GROUP,a))

    def test_read_does_not_initialize_or_call_provider(self):
        with patch('evidence_highlights.connect',return_value=database()),patch('evidence_highlights.init') as initialize,patch('evidence_highlights.decisions') as decide:
            result=highlights.enrich(TOPIC,GROUP,occurrence())
        self.assertEqual(result['highlight_status'],'not_prepared');initialize.assert_not_called();decide.assert_not_called()

    def test_missing_table_is_graceful(self):
        with patch('evidence_highlights.connect',side_effect=RuntimeError('unavailable')):
            self.assertEqual(highlights.enrich(TOPIC,GROUP,occurrence())['highlight_status'],'not_prepared')

    def test_coverage_has_no_new_highlight_work(self):
        with patch('evidence_highlights.connect') as connect:
            result=highlights.enrich(TOPIC,GROUP,occurrence('coverage'))
        self.assertEqual(result['highlight_status'],'not_applicable');connect.assert_not_called()

    def test_none_overrides_inconsistent_positive_sentences(self):
        p=packet();answers={'P0_NONE':dict(probability=.99)}
        for i,s in enumerate(p['sources']):
            for sentence in s['sentences']:answers[f'P0_E{i}_{sentence["id"]}']=dict(probability=.99)
        result=highlights.decode(p,0,answers)
        self.assertEqual(result['highlight_status'],'none');self.assertFalse(any(s['spans'] for s in result['sources']))

    def test_strict_threshold_selects_only_exact_witness_sentence(self):
        p=packet();answers={'P0_NONE':dict(probability=.01)}
        for i,s in enumerate(p['sources']):
            for sentence in s['sentences']:answers[f'P0_E{i}_{sentence["id"]}']=dict(probability=.2)
        answers['P0_E0_S1']=dict(probability=.85);answers['P0_E0_S2']=dict(probability=.849)
        result=highlights.decode(p,0,answers)
        self.assertEqual(result['highlight_status'],'ready');self.assertEqual(len(result['sources'][0]['spans']),1)
        s=result['sources'][0]['spans'][0];self.assertEqual(p['sources'][0]['quote'][s['start']:s['end']],s['text'])

    def test_refusals_and_missing_answers_never_force_marks(self):
        result=highlights.decode(packet(),0,{'P0_NONE':dict(type='refusal')})
        self.assertEqual(result['highlight_status'],'unassessed');self.assertFalse(any(s['spans'] for s in result['sources']))

    def test_existing_spans_preserved_without_mutating_input(self):
        original=occurrence();original['evidence'][0]['highlights']=[dict(start=0,end=3)]
        p=packet();answers={'P0_NONE':dict(probability=.01)}
        for i,s in enumerate(p['sources']):
            for sentence in s['sentences']:answers[f'P0_E{i}_{sentence["id"]}']=dict(probability=.1)
        answers['P0_E0_S2']=dict(probability=.95)
        payload=highlights.decode(p,0,answers);row=dict(status='done',payload=json.dumps(payload))
        with patch('evidence_highlights.connect',return_value=database(row)):result=highlights.enrich(TOPIC,GROUP,original)
        self.assertEqual(original['evidence'][0]['highlights'],[dict(start=0,end=3)])
        self.assertEqual(len(result['evidence'][0]['highlights']),2)

    def test_cached_offset_tampering_is_rejected(self):
        p=packet();payload=dict(highlight_status='ready',sources=[dict(lang=s['lang'],quote_hash=highlights.digest(s['quote']),spans=[]) for s in p['sources']])
        payload['sources'][0]['spans']=[dict(start=0,end=3,text='invented')]
        with patch('evidence_highlights.connect',return_value=database(dict(status='done',payload=json.dumps(payload)))):
            result=highlights.enrich(TOPIC,GROUP,occurrence())
        self.assertEqual(result['highlight_status'],'invalid_cache');self.assertFalse(any(e.get('highlights') for e in result['evidence']))

    def test_failed_cache_never_retries(self):
        with patch('evidence_highlights.connect',return_value=database(dict(status='failed',payload=None))),patch('evidence_highlights.decisions') as decide:
            result=highlights.enrich(TOPIC,GROUP,occurrence())
        self.assertEqual(result['highlight_status'],'failed');decide.assert_not_called()

    def test_preparation_scopes_batches_and_caps_occurrences(self):
        cases=[dict(topic=TOPIC,group=f'{i:064x}',occurrence=occurrence()) for i in range(18)]
        batches=[]
        def record(batch):batches.append(batch);return dict(ready=len(batch))
        with patch('evidence_highlights.init'),patch('evidence_highlights._reserve',return_value=True),patch('evidence_highlights.prepare_batch',side_effect=record):
            result=highlights.prepare(cases,workers=2)
        self.assertEqual(result['unique'],18);self.assertEqual(sum(len(b) for b in batches),18)
        self.assertTrue(all(len(b)<=16 for b in batches))
        self.assertTrue(all(len({(p['topic'],p['category'],tuple(s['lang'] for s in p['sources'])) for p in b})==1 for b in batches))

    def test_preparation_deduplicates_exact_scope_and_skips_reserved(self):
        case=dict(topic=TOPIC,group=GROUP,occurrence=occurrence())
        with patch('evidence_highlights.init'),patch('evidence_highlights._reserve',return_value=False),patch('evidence_highlights.decisions') as decide:
            result=highlights.prepare([case,deepcopy(case)])
        self.assertEqual(result['unique'],1);self.assertEqual(result['cached'],1);decide.assert_not_called()

    def test_model_change_cannot_reuse_another_models_cache(self):
        original=highlights.identity(TOPIC,GROUP,occurrence())[0]
        with patch('evidence_highlights.MODEL','different-model'):
            self.assertNotEqual(original,highlights.identity(TOPIC,GROUP,occurrence())[0])

    def test_oversized_single_packet_is_failed_without_provider(self):
        case=dict(topic=TOPIC,group=GROUP,occurrence=occurrence())
        with patch('evidence_highlights.init'),patch('evidence_highlights._reserve',return_value=True),patch('evidence_highlights.MAX_BATCH_BYTES',10),patch('evidence_highlights._store') as store,patch('evidence_highlights.decisions') as decide:
            result=highlights.prepare([case])
        self.assertEqual(result['failed'],1);self.assertEqual(result['batches'],0)
        self.assertEqual(store.call_args.args[1],'failed');decide.assert_not_called()

    def test_prompt_allows_none_and_keeps_original_sources(self):
        state,questions=highlights.request_for([packet()]);text=' '.join(q['instructions'] for q in questions)
        self.assertIn('never force a highlight',text);self.assertIn('unverified hypothesis',text)
        self.assertEqual(state['packets'][0]['sources'][0]['quote'],packet()['sources'][0]['quote'])
        self.assertTrue(all(q['type']=='predicate' for q in questions))


if __name__=='__main__':unittest.main()
