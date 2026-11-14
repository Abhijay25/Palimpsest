"""Offline corpus worker contracts; no DB, model downloads or provider calls."""
import contextlib
import io
import math
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from deploy import embed_corpus as e


def article(lang='en', page=1, topic='Q1'):
    return dict(lang=lang, page_id=page, wikidata_id=topic, rev_id=9, source_hash='a' * 64)


def cached(ordinal=0, text='One', heading='Intro'):
    return dict(ordinal=ordinal, heading=heading, text=text, model=e.MODEL,
                embedding=e.vector_bytes([.1] * 384))


class EmbeddingCorpusTests(unittest.TestCase):
    def test_cli_requires_explicit_scope_and_single_worker(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in ([], ['--limit', '0'], ['--all', '--limit', '3'], ['--all', '--workers', '2']):
                with self.assertRaises(SystemExit):
                    e.parser().parse_args(args)
        self.assertEqual(e.parser().parse_args(['--limit', '5']).limit, 5)
        self.assertTrue(e.parser().parse_args(['--all']).all)

    def test_existing_complete_vectors_are_reused(self):
        self.assertEqual(e.plan([('Intro', 'One')], [cached()]), ({0}, []))

    def test_partial_cache_fills_only_missing_ordinals(self):
        self.assertEqual(e.plan([('Intro', 'One'), ('Intro', 'Two')], [cached()]), ({0}, [1]))

    def test_stale_content_and_invalid_vectors_are_not_reused(self):
        row = cached()
        row['embedding'] = b'bad'
        self.assertEqual(e.plan([('Intro', 'One')], [row]), (set(), [0]))
        self.assertEqual(e.plan([('Intro', 'Changed')], [cached()]), (set(), [0]))

    def test_other_model_is_never_overwritten(self):
        row = cached()
        row['model'] = 'another-model'
        with self.assertRaisesRegex(RuntimeError, 'another model'):
            e.plan([('Intro', 'One')], [row])

    def test_dimension_and_nonfinite_validation(self):
        self.assertFalse(e.valid_vector(b''))
        self.assertFalse(e.valid_vector(e.vector_bytes([math.nan] * 384)))
        self.assertFalse(e.valid_vector(e.vector_bytes([0] * 384)))
        self.assertTrue(e.valid_vector(cached()['embedding']))

    def test_progress_requires_exact_source_and_contiguous_rows(self):
        c = MagicMock()
        row = dict(status='complete', policy=e.POLICY, source_hash='a' * 64,
                   source_rev=9, expected_passages=2, actual=2, matching=2,
                   first_ordinal=0, last_ordinal=1)
        c.fetchone.return_value = row
        self.assertTrue(e.completed(c, article()))
        row['last_ordinal'] = 2
        self.assertFalse(e.completed(c, article()))
        row['last_ordinal'] = 1
        row['source_hash'] = 'b' * 64
        self.assertFalse(e.completed(c, article()))

    def test_disk_guard_precedes_database_or_model(self):
        with patch.object(e.shutil, 'disk_usage', return_value=SimpleNamespace(free=e.MIN_FREE - 1)), \
             patch.object(e, 'connect') as conn:
            with self.assertRaisesRegex(RuntimeError, '512 MiB'):
                e.run(1)
            conn.assert_not_called()

    def test_eligibility_requires_two_supported_editions_without_default_limit(self):
        db, c = MagicMock(), MagicMock()
        db.__enter__.return_value = db
        db.cursor.return_value.__enter__.return_value = c
        c.fetchall.return_value = []
        with patch.object(e, 'connect', return_value=db):
            self.assertEqual(e.eligible(), [])
        sql, params = c.execute.call_args.args
        self.assertIn('HAVING COUNT(DISTINCT lang)>=2', sql)
        self.assertNotIn('LIMIT', sql)
        self.assertEqual(params, (*e.LANGS, *e.LANGS))

    def harness(self, insert_error=False):
        db, c, model = MagicMock(), MagicMock(), MagicMock()
        db.__enter__.return_value = db
        db.cursor.return_value.__enter__.return_value = c
        c.fetchone.side_effect = [dict(acquired=1), dict(text='One Two', rev_id=9, source_hash='a' * 64),
                                 dict(rev_id=9, source_hash='a' * 64)]
        c.fetchall.return_value = [cached()]
        model.embed.return_value = iter([[.2] * 384])
        if insert_error:
            c.executemany.side_effect = RuntimeError('test insertion failure')
        return db, c, model

    def test_article_commit_preserves_cache_and_uses_exact_prefix(self):
        db, c, model = self.harness()
        with patch.object(e, 'connect', return_value=db), patch.object(e, 'disk_guard'), \
             patch.object(e, 'completed', return_value=False), \
             patch.object(e, 'split_passages', return_value=[('Intro', 'One'), ('Intro', 'Two')]):
            result = e.process_article(article(), lambda: model)
        self.assertEqual(result, dict(status='complete', written=1, reused=1))
        model.embed.assert_called_once_with(['query: Two'], batch_size=8)
        db.begin.assert_called_once()
        db.commit.assert_called_once()
        db.rollback.assert_not_called()
        self.assertFalse(any('DELETE FROM passage' in str(call) for call in c.execute.call_args_list))
        self.assertTrue(any('RELEASE_LOCK' in str(call) for call in c.execute.call_args_list))

    def test_failed_article_rolls_back_and_marks_failed(self):
        db, c, model = self.harness(insert_error=True)
        with patch.object(e, 'connect', return_value=db), patch.object(e, 'disk_guard'), \
             patch.object(e, 'completed', return_value=False), \
             patch.object(e, 'split_passages', return_value=[('Intro', 'One'), ('Intro', 'Two')]):
            with self.assertRaises(RuntimeError):
                e.process_article(article(), lambda: model)
        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        self.assertTrue(any('failed' in str(call) for call in c.execute.call_args_list))

    def test_source_change_during_inference_never_publishes_vectors(self):
        db, c, model = self.harness()
        c.fetchone.side_effect = [dict(acquired=1), dict(text='One Two', rev_id=9, source_hash='a' * 64),
                                 dict(rev_id=10, source_hash='b' * 64)]
        with patch.object(e, 'connect', return_value=db), patch.object(e, 'disk_guard'), \
             patch.object(e, 'completed', return_value=False), \
             patch.object(e, 'split_passages', return_value=[('Intro', 'One'), ('Intro', 'Two')]):
            with self.assertRaisesRegex(RuntimeError, 'changed during'):
                e.process_article(article(), lambda: model)
        db.rollback.assert_called_once()
        db.commit.assert_not_called()
        c.executemany.assert_not_called()

    def test_cached_completion_never_loads_model(self):
        db, c, model = self.harness()
        getter = MagicMock(return_value=model)
        with patch.object(e, 'connect', return_value=db), patch.object(e, 'disk_guard'), \
             patch.object(e, 'completed', return_value=True):
            self.assertEqual(e.process_article(article(), getter)['status'], 'cached')
        getter.assert_not_called()

    def test_pilot_limit_advances_past_completed_topics(self):
        db, c = MagicMock(), MagicMock()
        db.__enter__.return_value = db
        db.cursor.return_value.__enter__.return_value = c
        rows = [article(topic='Q1'), article(page=2, topic='Q2'), article(page=3, topic='Q3')]
        with patch.object(e, 'disk_guard'), patch.object(e, 'init'), \
             patch.object(e, 'connect', return_value=db), patch.object(e, 'eligible', return_value=rows), \
             patch.object(e, 'completed', side_effect=[True, False, False]), \
             patch.object(e, 'durable_status', return_value=[]), \
             patch.object(e, 'process_article', return_value=dict(status='complete', written=2, reused=0)) as process, \
             contextlib.redirect_stdout(io.StringIO()):
            totals = e.run(limit=1)
        self.assertEqual(totals['attempted_topics'], 1)
        self.assertEqual(process.call_args.args[0]['wikidata_id'], 'Q2')
        process.assert_called_once()

    def test_offline_cpu_model_contract(self):
        import sys
        fake = MagicMock()
        fake.TextEmbedding.list_supported_models.return_value = [{'model': e.MODEL}]
        descriptions = MagicMock()
        with patch.dict(sys.modules, {'fastembed': fake, 'fastembed.common.model_description': descriptions}), \
             patch.dict(e.os.environ, {}, clear=False):
            e.load_model()
        kwargs = fake.TextEmbedding.call_args.kwargs
        self.assertEqual(kwargs['model_name'], e.MODEL)
        self.assertTrue(kwargs['local_files_only'])
        self.assertEqual(kwargs['providers'], ['CPUExecutionProvider'])
        self.assertEqual(kwargs['threads'], 1)


if __name__ == '__main__':
    unittest.main()
