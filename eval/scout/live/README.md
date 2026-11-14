# Live Wikipedia scout (2026-11-14)
All data from the MediaWiki Action API (en/sv/fi), UA "Palimpsest-MVP/0.1 (hackathon research)", <=1 req/s. Scripts: ../tools/{wp,fd,dl,dl_fi,disc,filt}.py.

## future_dates.jsonl (20; en 5, sv 9->8 kept, fi 7)
Queries (list=search, srnamespace=0, CirrusSearch regex): en `insource:/access-date *= *202[789]/`, `... [0-9]+ (December|November) 2026/`, `(December|Nov..) d, 2026`, `Retrieved d M 2027`; sv `hämtdatum *= *202[789]/`, `hämtdatum *= *[0-9]+ december 2026`, `2026-12`; fi `viitattu *= *[0-9. a-zä]*202[789]/`, `viitattu *= *2026-12`, arkistoitu/arkivdatum/archive-date variants.
Each candidate fetched with action=parse (text|wikitext|revid); kept only if the RENDERED text shows keyword (Retrieved/Läst/Hämtad/Viitattu) followed by a date > 2026-11-14 (strict regex, offline filter filt.py; first loose regex gave false positives, removed). 27 passed, 7 trimmed for duplicates/spread. Note: revid is the revision at fetch time; the "date later than page's latest revision" case is subsumed (all dates > today). Many sv/fi hits look like year typos (2025->2027/28/29), not malicious.
Not done: day+month-without-year template cases (no reliable regex found within budget); en `access-date=2026-12` and `archive-date` queries returned 0.

## dead_links.jsonl (13) / controls.jsonl (17)
Templates discovered from the wikis (disc.py -> deadlink_templates.json): en `Template:Dead link` (+32 redirects e.g. Dl, Deadlink, 404, Broken link, Linkbroken); sv `Mall:Död länk` (+Dead link, 404, Dödlänk, Dl, Deadlink, Toter Link); fi `Malline:Kuollut linkki` (no redirects).
Candidate pages: `hastemplate:"Dead link" incategory:"All articles with dead external links"`, `hastemplate:"Död länk"`, `hastemplate:"Kuollut linkki"` with srsort=random, srlimit=50, keep size<20000 bytes. (Earlier `insource:/\{\{Dead link/` regex timed out / returned only huge pages; fi regex returned 0.)
Per page: parse wikitext; refs (<ref>..</ref>) with a URL are "marked" if they hold a dead-link template or an archive-url/arkivurl/arkisto param, else control. first_cited = earliest revision whose wikitext contains the URL; marked = earliest revision where the ref containing the URL carries the same mark kind; both by binary search (<=15 fetches each) over prop=revisions rvdir=newer (history <=1500 revs, else page skipped).
marked_how: "dead-link template" or "archive-url added" (the latter does NOT imply the link is dead; en archive-url is routine). "url replaced" never found/attempted.
Controls: up to 2 unmarked-ref URLs per case page, same fields minus marked_*. Their "unmarked" status is as of the current revision (see current_revid).

## Biases / failures
- Binary search assumes monotone presence; non-monotone histories give wrong revisions (one such case, sv Leppävirta, dropped because marked < first cited). Others not verified.
- Size<20000 bytes and history<=1500 revs favour small, rarely edited pages; big en articles skipped.
- Several candidates dropped as "nomk" (mark not found in later revisions or at current ref match, e.g. template placed outside ref).
- claim_sentence is heuristic (text before the ref, markup stripped); some are fragments (e.g. Leppävirta-like list items, Modern asatro).
- Marked dates mostly 2024-2026: the dead mark is recent, so long gaps between citation and marking are over-represented in en.
- fd.py found dates via search index lag: only pages the index has updated.
- Dead-link template presence is Wikipedia's record, not verification that the URL is currently dead.
