"""Real reference-section failure and fresh preparation identities; no models/DB."""
import unittest
from unittest.mock import MagicMock,patch
from tokenizers import Tokenizer,models,pre_tokenizers
from pipeline import split_article,PASSAGE_VERSION
import historical_divergence as storage


class PassageEligibilityTests(unittest.TestCase):
    def tokenizer(self):
        tokenizer=Tokenizer(models.WordLevel({'[UNK]':0},unk_token='[UNK]'))
        tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
        return tokenizer

    def test_real_reference_entry_excluded_and_prose_offsets_preserved(self):
        prose='Haminan rauhansopimus solmittiin vuonna 1809.'
        reference='Freds fördraget i Fredrikshamn / Haminan rauhansopimus 17.9.1809 Pauli Kruhse.'
        text='## Historia\n'+prose+'\n\n## Aiheesta muualla\n'+reference
        parts=list(split_article(dict(lang='fi',rev_id=123,text=text),self.tokenizer()))
        self.assertEqual([p['text'] for p in parts],[prose])
        self.assertEqual(text[parts[0]['start']:parts[0]['end']],prose)

    def test_language_and_exact_heading_control_exclusion(self):
        for lang,heading,excluded in [('fi',' AIHEESTA  MUUALLA ',True),('en','Aiheesta muualla',False),('fi','Aiheesta muualla sodan aikana',False)]:
            with self.subTest(lang=lang,heading=heading):
                text='## '+heading+'\nThis source passage must retain its exact text.'
                parts=list(split_article(dict(lang=lang,rev_id=1,text=text),self.tokenizer()))
                self.assertEqual(bool(parts),not excluded)

    def test_revised_preparation_never_reuses_legacy_revision_identity(self):
        db=MagicMock();cursor=db.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value={'ready':True}
        model=MagicMock()
        with patch('historical_divergence.connect',return_value=db):
            identity=storage.index_revision('fi',{'revid':123},model,topic='Q1')
        legacy=storage.digest([storage.VERSION,'Q1','fi',123])
        self.assertNotEqual(identity,legacy)
        self.assertEqual(identity,storage.digest([storage.VERSION,PASSAGE_VERSION,'Q1','fi',123]))
        self.assertEqual(cursor.execute.call_count,1)
        model.embed.assert_not_called()


if __name__=='__main__':unittest.main()
