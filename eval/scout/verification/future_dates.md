# Citation-date check on the isolated scout's real future dates (2026-11-14)

Cases: eval/scout/live/future_dates.jsonl — 20 live-Wikipedia citations whose rendered date is after the revision (en 5, sv 8, fi 7), found and confirmed on the rendered page by an isolated scout that never saw our code. Script: verify_future_dates.py (fetches each revision's wikitext, extracts the <ref> holding the date, runs `scan_changed_citation_dates` with `now` = that revision's timestamp). Deterministic check, no model calls.

Result: **19/20 caught** (en 4/5, sv 8/8, fi 7/7), each finding the exact rendered date. Formats covered: ISO (2027-04-27), English long form, Swedish month names, Finnish d.m.yyyy.

Open: List of accolades received by Netflix (en, 2027-10-21 in a table-row {{cite web}}) is missed even with <ref>-bounded extraction; not yet diagnosed (extraction vs. rendering in a table context).

Not covered by this set: year-less dates (the Tornedalingar pattern) — the scout's searches found none; the Tornedalingar case remains the only real example.
