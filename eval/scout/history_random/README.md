# Random Wikipedia history test set (scouted 2026-11-15)

## Procedure
list=random (generator, ns 0) -> skip disambiguation (pageprops), 'List of'-style titles, <3000 bytes, <20 revisions (newest 100 fetched). Edits from last 2 years (>=2024-11-15) from newest 100 revisions. Skipped: bots (user group bot or name ending 'bot'), tagged mw-revert/undo/rollback/manual-revert, |size delta|<20, same user as preceding revision, no added sentence >=25 chars. Labels from later history only: reverted = sha1 of later rev (<=30 revs, other user) equals parent sha1, or mw-reverted tag with a later undo/rollback rev; corrected = within next 10 revs a different user removed a sentence E added and replaced it with a similar one (difflib>=0.5; deletion-only skipped); stood = all added sentences still in the revision current at E+30d, no correction. Max 3 edits per article, 1 req/s, quotas 12/12/16, first-come within quota.

## Counts

### en: {'reverted': 12, 'corrected': 12, 'stood': 16}, articles distinct 22, articles scanned 116, candidate edits (last 2y) 857
Skips: edit: |size change|<20=366; edit: same user as preceding rev=146; edit: label quota full=127; edit: bot=42; edit: is revert/undo/rollback=42; article: disambig/list/short=40; edit: stood unverifiable (<30d or no data)=27; edit: no later history=11; article: <20 revisions=11; edit: no substantive added sentence=9; edit: text gone by +30d without attributable correction=4; edit: only deleted by later editor (ambiguous)=2; edit: mw-reverted but reverting rev not found=2

### sv: {'reverted': 5, 'corrected': 12, 'stood': 16}, articles distinct 25, articles scanned 2560, candidate edits (last 2y) 570
Skips: article: disambig/list/short=1876; article: <20 revisions=491; edit: |size change|<20=222; edit: same user as preceding rev=126; edit: bot=47; edit: label quota full=32; edit: no later history=31; edit: stood unverifiable (<30d or no data)=30; edit: is revert/undo/rollback=18; edit: no substantive added sentence=14; edit: text gone by +30d without attributable correction=11; edit: only deleted by later editor (ambiguous)=2; edit: mw-reverted but reverting rev not found=1

### fi: {'reverted': 12, 'corrected': 12, 'stood': 16}, articles distinct 26, articles scanned 1101, candidate edits (last 2y) 1308
Skips: article: disambig/list/short=574; edit: |size change|<20=487; edit: same user as preceding rev=368; article: <20 revisions=243; edit: label quota full=175; edit: bot=102; edit: is revert/undo/rollback=44; edit: stood unverifiable (<30d or no data)=21; edit: no later history=20; edit: text gone by +30d without attributable correction=16; edit: no substantive added sentence=11; edit: mw-reverted but reverting rev not found=2; edit: only deleted by later editor (ambiguous)=1

## Biases
- sv is short of reverted (5/12): reverts were very rare among 2560 random sv articles (most articles are short bot stubs/<20 revisions); stood/corrected filled.
- Only the newest 100 revisions are seen, so heavily edited articles are represented by recent edits only; edits need >=20 revisions (favors active articles).
- Quota is first-come: once corrected/stood fill, later candidates are not examined, so the order of random draws matters, not uniform over all edits.
- Sentence-level heuristics on raw wikitext (refs/templates count as text); 'corrected' includes any later different-user rewrite, not necessarily a fix; 'stood' means text present at +30d, not that it is correct. Reverted via sha1 favors vandalism/obvious reverts; reverts by same user excluded.
- Anonymous = IP username. Stood edits require E older than 30 days, biasing against recent edits.
