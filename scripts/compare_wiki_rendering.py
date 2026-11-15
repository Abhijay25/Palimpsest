"""Compare captured exact-revision parser responses offline; never asserts visual parity."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path


class ArticleText(HTMLParser):
    """Retain article/citation text while excluding explicitly identified UI."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    def __init__(self):
        super().__init__()
        self.stack = []
        self.text = []
        self.images = self.references = self.errors = 0
        self.reference_notes = self.citation_bodies = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        self.images += tag == 'img'
        self.references += tag == 'sup' and 'reference' in classes
        self.errors += bool(classes & {'error', 'scribunto-error', 'mw-ext-cite-error'})
        parent = self.stack[-1] if self.stack else ('', False, False, False)
        skip = parent[1] or tag in {'style', 'script'} or bool(classes & {'toc', 'mw-editsection', 'mw-cite-backlink'})
        note = parent[2] or (tag == 'li' and attrs.get('id', '').startswith('cite_note'))
        citation = parent[3] or (note and 'reference-text' in classes)
        self.reference_notes += tag == 'li' and attrs.get('id', '').startswith('cite_note')
        self.citation_bodies += note and 'reference-text' in classes and not parent[3]
        if tag not in self.VOID:
            self.stack.append((tag, skip, note, citation))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        if not self.stack or (not self.stack[-1][1] and (not self.stack[-1][2] or self.stack[-1][3])):
            self.text.append(text)


def compare(source, native, source_revision, local_revision):
    parsed = []
    for response, expected in [(source, source_revision), (native, local_revision)]:
        page = response.get('response', response)['parse']
        if page.get('revid') != expected:
            raise ValueError('Captured parser response does not match its explicitly selected revision.')
        parsed.append(page)
    if parsed[0]['title'].replace('_', ' ') != parsed[1]['title'].replace('_', ' '):
        raise ValueError('Captured source and local article titles differ.')
    text = []
    summaries = []
    for page in parsed:
        reader = ArticleText()
        reader.feed(page['text'])
        if reader.reference_notes != reader.citation_bodies:
            raise ValueError('Unsupported citation markup; cannot safely separate citation text from backlink controls.')
        words = ' '.join(reader.text).split()
        text.append(words)
        summaries.append(dict(revision=page['revid'], page=page.get('pageid'), words=len(words),
            html_sha256=hashlib.sha256(page['text'].encode()).hexdigest(),
            images=reader.images, reference_markers=reader.references, error_nodes=reader.errors,
            headings=[section['line'] for section in page.get('sections', [])]))
    matcher = SequenceMatcher(None, *text, autojunk=False)
    return dict(title=parsed[0]['title'], source=summaries[0], native=summaries[1],
        identical_normalized_text=text[0] == text[1],
        differences=[dict(kind=kind, source=' '.join(text[0][a:b]), native=' '.join(text[1][c:d]))
            for kind, a, b, c, d in matcher.get_opcodes() if kind != 'equal'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--source-revision', type=int, required=True)
    parser.add_argument('--local-revision', type=int, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.source.read_text(encoding='utf-8')),
        json.loads(args.native.read_text(encoding='utf-8')), args.source_revision, args.local_revision)
    result['checked_at'] = datetime.now(timezone.utc).isoformat()
    result['scope'] = ('Offline diagnostic only. Excludes styles/scripts, table of contents, edit controls and citation backlinks. '
        'Text equality does not establish image identity/loading, layout, interaction or historical transclusion parity. '
        'Source/local revision reconciliation must be verified separately.')
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    else:
        print(output)


if __name__ == '__main__':
    main()
