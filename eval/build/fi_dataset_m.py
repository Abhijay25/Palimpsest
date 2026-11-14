"""Build Finnish revert and control cases from dataset M (fi.wikipedia history of Finland)."""

import argparse
import difflib
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from palimpsest.schema import Case, dump_jsonl
from palimpsest.stage0 import (
    extract_ref_urls,
    refs_for_changed_sentences,
    strip_wikitext,
)

SEED = 1114
DATA_DIR = Path("data/m")
OUT_DIR = Path("eval/cases")
REVERT_COUNT = 8
CONTROL_COUNT = 6
MAX_NO_REF_SHARE = 1 / 3
RECENT_YEAR = 2015
MAX_TEXT_CHARS = 1500
MIN_ADDED_WORDS = 5
CONTROL_BYTES = (30, 600)
CONTROL_LOOKAHEAD = 10
CONTROL_POOL = 1200
PRIORITY_POOL = 400
POV_COMMENT = re.compile(
    r"(?i)(n?pov|puolueet|näkökulm|mielipi|spekul|tulkin|lähteet|wp:ei|wp:ttt)"
)
NON_PROSE_START = ("{", "|", "*", "#", ":", ";", "!", "=", "<!--", "__")
NON_PROSE_LINE = re.compile(r"(?m)^\s*(\||\{\||\|\}|\*|#|:|;|!|\{\{)")
NON_PROSE_LINK = re.compile(
    r"(?i)^(\[\[(luokka|category|tiedosto|kuva|file|image):|thumb\||pienoiskuva\|)",
    re.UNICODE,
)
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
# rev_ids dropped after manual review (unusable cases); builder then takes the next candidate.
EXCLUDED_REV_IDS: frozenset[int] = frozenset({17052831})
METADATA_COLUMNS = [
    "page_id",
    "title",
    "rev_id",
    "parent_id",
    "timestamp",
    "user",
    "anonymous",
    "comment",
    "minor",
    "sha1",
    "bytes",
]


@dataclass
class Version:
    page_id: int
    title: str
    rev_id: int
    year: int
    anonymous: bool
    comment: str
    minor: bool
    sha1: str
    size: int


@dataclass
class Candidate:
    kind: str
    rev_id: int
    old_rev: int
    new_rev: int
    title: str
    year: int
    comment: str
    matches_pov: bool


@dataclass
class Extracted:
    old_text: str
    new_text: str
    ref_urls: list[str]
    old_wikitext: str
    new_wikitext: str
    changed_ref_urls: list[str]


def load_versions() -> dict[int, list[Version]]:
    tables = [
        pq.read_table(path, columns=METADATA_COLUMNS)
        for path in sorted(DATA_DIR.glob("versions-*.parquet"))
    ]
    rows = pa.concat_tables(tables).to_pylist()
    rows.sort(key=lambda r: (r["page_id"], r["timestamp"], r["rev_id"]))
    pages: dict[int, list[Version]] = {}
    for r in rows:
        pages.setdefault(r["page_id"], []).append(
            Version(
                page_id=r["page_id"],
                title=r["title"],
                rev_id=r["rev_id"],
                year=r["timestamp"].year,
                anonymous=bool(r["anonymous"]),
                comment=r["comment"] or "",
                minor=bool(r["minor"]),
                sha1=r["sha1"] or "",
                size=int(r["bytes"]),
            )
        )
    return pages


def revert_candidates(pages: dict[int, list[Version]]) -> list[Candidate]:
    found: list[Candidate] = []
    for versions in pages.values():
        for i in range(2, len(versions)):
            cur, mid, before = versions[i], versions[i - 1], versions[i - 2]
            if cur.sha1 and cur.sha1 == before.sha1 and mid.sha1 != cur.sha1:
                found.append(
                    Candidate(
                        "revert",
                        cur.rev_id,
                        before.rev_id,
                        mid.rev_id,
                        cur.title,
                        cur.year,
                        cur.comment,
                        bool(POV_COMMENT.search(cur.comment)),
                    )
                )
    return found


def control_candidates(pages: dict[int, list[Version]]) -> list[Candidate]:
    found: list[Candidate] = []
    for versions in pages.values():
        for i in range(1, len(versions)):
            cur, prev = versions[i], versions[i - 1]
            if cur.anonymous or cur.minor or not cur.comment.strip():
                continue
            if not CONTROL_BYTES[0] <= abs(cur.size - prev.size) <= CONTROL_BYTES[1]:
                continue
            if cur.sha1 == prev.sha1:
                continue
            if i >= 2 and cur.sha1 == versions[i - 2].sha1:
                continue
            window = versions[i + 1 : i + 1 + CONTROL_LOOKAHEAD]
            if any(v.sha1 == prev.sha1 for v in window):
                continue
            found.append(
                Candidate(
                    "control",
                    cur.rev_id,
                    prev.rev_id,
                    cur.rev_id,
                    cur.title,
                    cur.year,
                    cur.comment,
                    False,
                )
            )
    return found


def load_texts(rev_ids: set[int]) -> dict[int, str]:
    texts: dict[int, str] = {}
    for path in sorted(DATA_DIR.glob("versions-*.parquet")):
        pf = pq.ParquetFile(path)
        for group in range(pf.metadata.num_row_groups):
            table = pf.read_row_group(group, columns=["rev_id", "text"])
            for rev_id, text in zip(
                table["rev_id"].to_pylist(), table["text"].to_pylist(), strict=True
            ):
                if rev_id in rev_ids:
                    texts[rev_id] = text or ""
    return texts


def is_prose_paragraph(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped or stripped.startswith(NON_PROSE_START):
        return False
    if NON_PROSE_LINK.match(stripped) or NON_PROSE_LINE.search(stripped):
        return False
    plain = strip_wikitext(stripped).strip()
    return 0 < len(plain) <= MAX_TEXT_CHARS and any(c.isalnum() for c in plain)


def added_words(old_plain: str, new_plain: str) -> int:
    old_words = Counter(w.lower() for w in WORD_RE.findall(old_plain))
    new_words = Counter(w.lower() for w in WORD_RE.findall(new_plain))
    return sum((new_words - old_words).values())


def extract_changed_paragraph(old_wikitext: str, new_wikitext: str) -> Extracted | None:
    old_paras = [p.strip() for p in re.split(r"\n+", old_wikitext) if p.strip()]
    new_paras = [p.strip() for p in re.split(r"\n+", new_wikitext) if p.strip()]
    best: tuple[int, Extracted] | None = None
    matcher = difflib.SequenceMatcher(a=old_paras, b=new_paras, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in ("replace", "insert"):
            continue
        olds = old_paras[i1:i2]
        for offset, new_para in enumerate(new_paras[j1:j2]):
            old_para = olds[offset] if offset < len(olds) else ""
            if not is_prose_paragraph(new_para):
                continue
            if old_para and not is_prose_paragraph(old_para):
                continue
            new_plain = strip_wikitext(new_para).strip()
            old_plain = strip_wikitext(old_para).strip() if old_para else ""
            if new_plain == old_plain:
                continue
            urls = extract_ref_urls(new_para)
            changed_urls = refs_for_changed_sentences(old_para, new_para)
            score = (
                10 * len(urls) + (20 if changed_urls else 0) + (5 if old_para else 0)
            )
            if best is None or score > best[0]:
                best = (
                    score,
                    Extracted(
                        old_plain, new_plain, urls, old_para, new_para, changed_urls
                    ),
                )
    return best[1] if best else None


def select(
    candidates: list[Candidate],
    texts: dict[int, str],
    count: int,
    rng: random.Random,
    require_added_words: bool,
) -> list[tuple[Candidate, Extracted]]:
    """Pick cases: POV-regex matches first, refs preferred, recent preferred, capped no-ref share."""
    max_no_ref = int(count * MAX_NO_REF_SHARE)
    rng.shuffle(candidates)
    tiers: list[tuple[Candidate, Extracted]] = []
    seen_titles: set[str] = set()
    for cand in candidates:
        if cand.rev_id in EXCLUDED_REV_IDS or cand.title in seen_titles:
            continue
        old_wt, new_wt = texts.get(cand.old_rev), texts.get(cand.new_rev)
        if old_wt is None or new_wt is None:
            continue
        extracted = extract_changed_paragraph(old_wt, new_wt)
        if extracted is None:
            continue
        if require_added_words and (
            added_words(extracted.old_text, extracted.new_text) < MIN_ADDED_WORDS
        ):
            continue
        seen_titles.add(cand.title)
        tiers.append((cand, extracted))
    tiers.sort(
        key=lambda t: (
            not t[0].matches_pov,
            not t[1].changed_ref_urls,
            not t[1].old_text,
            t[0].year < RECENT_YEAR,
        )
    )
    chosen: list[tuple[Candidate, Extracted]] = []
    no_ref = 0
    for cand, extracted in tiers:
        if len(chosen) >= count:
            break
        if not extracted.changed_ref_urls:
            if no_ref >= max_no_ref:
                continue
            no_ref += 1
        chosen.append((cand, extracted))
    return chosen


def to_case(cand: Candidate, extracted: Extracted, expected: str, bucket: str) -> Case:
    prefix = "fi_revert" if cand.kind == "revert" else "fi_control"
    return Case.model_validate(
        {
            "case_id": f"{prefix}_{cand.rev_id}",
            "lang": "fi",
            "bucket": bucket,
            "provenance": (
                "https://fi.wikipedia.org/w/index.php?"
                f"diff={cand.new_rev}&oldid={cand.old_rev}"
            ),
            "page_title": cand.title,
            "old_text": extracted.old_text,
            "new_text": extracted.new_text,
            "ref_urls": extracted.ref_urls,
            "old_wikitext": extracted.old_wikitext,
            "new_wikitext": extracted.new_wikitext,
            "changed_ref_urls": extracted.changed_ref_urls,
            "expected": expected,
            "notes": cand.comment,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reverts", type=int, default=REVERT_COUNT)
    parser.add_argument("--controls", type=int, default=CONTROL_COUNT)
    args = parser.parse_args()
    rng = random.Random(SEED)
    pages = load_versions()
    reverts = revert_candidates(pages)
    controls = control_candidates(pages)
    print(f"revert candidates: {len(reverts)}, control candidates: {len(controls)}")
    pov_hits = [c for c in reverts if c.matches_pov]
    print(f"revert candidates matching POV regex: {len(pov_hits)}")
    recent_controls = [c for c in controls if c.year >= RECENT_YEAR]
    rng.shuffle(recent_controls)
    control_pool = recent_controls[:CONTROL_POOL]
    rng.shuffle(pov_hits)
    others = [c for c in reverts if not c.matches_pov]
    rng.shuffle(others)
    revert_pool = pov_hits + others
    needed = {r for c in revert_pool + control_pool for r in (c.old_rev, c.new_rev)}
    texts = load_texts(needed)
    pov_selected = select(pov_hits, texts, args.reverts, rng, False)
    selected = pov_selected
    if len(selected) < args.reverts:
        selected = select(revert_pool, texts, args.reverts, rng, True)
    print(
        f"reverts selected: {len(selected)} "
        f"(POV regex: {sum(c.matches_pov for c, _ in selected)}, "
        f"relaxed fallback: {sum(not c.matches_pov for c, _ in selected)})"
    )
    revert_cases = [to_case(c, e, "UNLABELLED", "fi_revert") for c, e in selected]
    control_cases = [
        to_case(c, e, "CLEAN_PASS", "fi_control")
        for c, e in select(control_pool, texts, args.controls, rng, False)
    ]
    dump_jsonl(OUT_DIR / "fi_reverts.jsonl", revert_cases)
    dump_jsonl(OUT_DIR / "fi_controls.jsonl", control_cases)
    print(f"wrote {len(revert_cases)} reverts, {len(control_cases)} controls")


if __name__ == "__main__":
    main()
