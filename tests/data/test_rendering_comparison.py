import unittest
from scripts.compare_wiki_rendering import ArticleText, compare


class RenderingComparisonTests(unittest.TestCase):
    def test_old_and_new_citation_controls_leave_the_same_citation_body(self):
        old = '<p>A real assertion^2.<sup class="reference">[1]</sup></p><ol><li id="cite&#95;note-1">^ [<a>a</a>] <span class="reference-text">Real cited text</span></li></ol>'
        new = '<p>A real assertion^2.<sup class="reference">[1]</sup></p><ol><li id="cite_note-1"><span class="mw-cite-backlink">↑</span><span class="reference-text">Real cited text</span></li></ol>'
        readers = []
        for markup in [old, new]:
            reader = ArticleText(); reader.feed(markup); readers.append(reader)
        self.assertEqual(readers[0].text, readers[1].text)
        self.assertIn('A real assertion^2.', readers[0].text)
        self.assertIn('Real cited text', readers[0].text)
        self.assertEqual(readers[0].references, 1)

    def test_missing_prose_media_and_errors_are_not_hidden_by_ui_normalization(self):
        source = {'parse': {'revid': 100, 'pageid': 8, 'title': 'Real article', 'text': '<p>Original evidence</p><img src="source.jpg">', 'sections': [{'line': 'History'}]}}
        native = {'parse': {'revid': 2, 'pageid': 1, 'title': 'Real_article', 'text': '<style>CSS only</style><strong class="error">Missing module</strong>', 'sections': []}}
        result = compare(source, native, 100, 2)
        self.assertFalse(result['identical_normalized_text'])
        self.assertEqual(result['source']['images'], 1)
        self.assertEqual(result['native']['images'], 0)
        self.assertEqual(result['native']['error_nodes'], 1)
        self.assertTrue(any('Original evidence' in diff['source'] for diff in result['differences']))
        self.assertNotIn('CSS only', str(result['differences']))
        with self.assertRaises(ValueError): compare(source, native, 100, 100)
        native['parse']['title'] = 'Another article'
        with self.assertRaises(ValueError): compare(source, native, 100, 2)

    def test_unknown_citation_markup_fails_instead_of_dropping_cited_text(self):
        source = {'parse': {'revid': 100, 'title': 'Article', 'text': '<ol><li id="cite_note-1">Real citation without a recognized wrapper</li></ol>'}}
        native = {'parse': {'revid': 2, 'title': 'Article', 'text': '<p>No citation</p>'}}
        with self.assertRaisesRegex(ValueError, 'Unsupported citation markup'):
            compare(source, native, 100, 2)
