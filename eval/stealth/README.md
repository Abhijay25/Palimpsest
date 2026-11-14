# Stealth scanner evaluation set

JSONL, one case per line, fields: `case_id, lang, bucket, provenance, target_type, old_text, text, expected_status, notes`
(matches `StealthCase` in `palimpsest/stealth/eval.py`). `expected_status` is a `StealthStatus` value.

| File | Cases | Source |
|---|---|---|
| `cases/attacks_spec.jsonl` | 7 | Spec section 7 Step 2, verbatim. Case 7 status is our reading (spec gives none): lure is an AI instruction. |
| `cases/attacks_evasion.jsonl` | 20 | Hand-written evasions (split comments, casing/spacing, zero-width splitting, homoglyph, bidi, JSON-LD, aria-label, template params, Finnish-language payloads, an entity-encoded trap). Notes say what a correct scanner does and flag cases a regex scanner likely misses. |
| `cases/benign_real_fi.jsonl` | 36 | Real parent->child revisions in `data/m/versions-0{1,2}.parquet`; seeded `random.Random(1114)`; +-600 char windows around the added channel; diff URL in `provenance`. |
| `cases/benign_real_en.jsonl` | 6 | Real en.wikipedia recent edits via the MediaWiki API (rate-limited, 150 request cap). |

## Labelling rules
- Hidden text with an instruction aimed at an AI/summariser/verifier (any language): `CRITICAL_AI_POISONING`. It outranks CSS/homoglyph/invisible-char findings.
- Hidden or cloaked content (display:none, near-zero font, white-on-white, off-screen, `hidden`) without an instruction, e.g. a defamatory claim: `CSS_CLOAKING_DETECTED`.
- Mixed-script tokens (Latin plus Cyrillic/Greek) or bidi overrides altering rendering: `HOMOGLYPH_SPOOFING`.
- Ordinary editor comments and commented-out content with no instruction: `BENIGN_NOTES_ONLY`.
- Visible layout styling, alt text (empty or descriptive), stray soft hyphens/ZWNJ/LRM/BOM from copy-paste, entity-encoded text that renders visibly: `CLEAN`.
- Real-data labels were assigned by manual reading; uncertain ones say so in `notes`. Real channels with no real example (mw-collapsible, hidden CSS, zero-width/tag payloads, genuine prompt injections) appear only in the synthetic buckets.

## Rebuild
Builders live in `build/` (run with `nix develop -c uv run python`): `attacks.py`; `mine_fi.py` -> `sample_fi.py` -> `build_fi.py`; `mine_en.py` -> `build_en.py`. Real-data builders take scratch paths as arguments; the label tables in `build_fi.py`/`build_en.py` are indexed against the seeded sample.
