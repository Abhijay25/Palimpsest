"""Build eval/cases/en_reverts.jsonl (UNLABELLED) and en_controls.jsonl (CLEAN_PASS) from English Wikipedia."""

import argparse
import difflib
import random
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import httpx
from pydantic import BaseModel

from palimpsest.schema import Case, dump_jsonl, load_cases
from palimpsest.stage0 import (
    extract_ref_urls,
    refs_for_changed_sentences,
    strip_wikitext,
)

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "Palimpsest-MVP/0.1 (hackathon research)"
REVERTS_PATH = Path("eval/cases/en_reverts.jsonl")
CONTROLS_PATH = Path("eval/cases/en_controls.jsonl")
N_CASES = 10
DEFAULT_SEED = 1114
MAX_NO_REF_SHARE = 1 / 3
MAX_CHARS = 1500
MIN_SIMILARITY = 0.6
MAX_PER_PAGE = {"en_revert": 2, "en_control": 1}
POV_RE = re.compile(
    r"(?i)\b(n?pov|neutral|synth|original research|editoriali[sz]|puffery|peacock|weasel|undue|biased)\b"
)
# Widened regex, used only when POV_RE yields too few usable reverts.
WIDE_RE = re.compile(
    r"(?i:\bunsourced\b|\bWP:V\b|\bWP:OR\b|\bunreferenced\b|\bpromotional\b|\bspam\b)|\bOR\b"
)
REVERT_WORDS_RE = re.compile(r"(?i)\b(revert|undid|undo|rv|rollback|vandal\w*)\b")
NON_PROSE_START = (
    "{|",
    "|",
    "*",
    "#",
    "{{",
    "[[Category",
    "[[File",
    "[[Image",
    "==",
    ":",
    ";",
    "!",
    "<!--",
)
SESSION_SLEEP_S = 1.5


class RecentChange(BaseModel):
    revid: int
    old_revid: int
    title: str
    comment: str
    sizediff: int


class Revision(TypedDict):
    parentid: int
    text: str


class Candidate(BaseModel):
    case: Case
    pov: bool
    has_ref: bool


def api_get(client: httpx.Client, params: dict[str, str | int]) -> dict[str, object]:
    full: dict[str, str | int] = {
        "format": "json",
        "formatversion": 2,
        "maxlag": 5,
        **params,
    }
    for attempt in range(3):
        try:
            resp = client.get(API_URL, params=full)
            resp.raise_for_status()
            data: dict[str, object] = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"http error: {exc!r}", flush=True)
            time.sleep(10 * (attempt + 1))
            continue
        time.sleep(SESSION_SLEEP_S)
        if "error" in data:  # maxlag or transient API error
            print(f"api error: {data['error']}", flush=True)
            time.sleep(3 * (attempt + 1))
            continue
        return data
    return {}


def recent_changes(
    client: httpx.Client, extra: dict[str, str | int], pages: int
) -> list[RecentChange]:
    out: list[RecentChange] = []
    params: dict[str, str | int] = {
        "action": "query",
        "list": "recentchanges",
        "rctype": "edit",
        "rcnamespace": 0,
        "rcprop": "title|ids|comment|tags|sizes",
        "rclimit": 500,
        **extra,
    }
    for _ in range(pages):
        data = api_get(client, params)
        query = data.get("query")
        if not isinstance(query, dict):
            break
        for rc in query.get("recentchanges", []):
            if "mw-reverted" in rc.get("tags", []) and extra.get("rctag") is None:
                continue
            if not rc.get("old_revid"):
                continue
            out.append(
                RecentChange(
                    revid=rc["revid"],
                    old_revid=rc["old_revid"],
                    title=rc["title"],
                    comment=rc.get("comment", ""),
                    sizediff=rc.get("newlen", 0) - rc.get("oldlen", 0),
                )
            )
        cont = data.get("continue")
        if not isinstance(cont, dict):
            break
        params = {**params, **{k: str(v) for k, v in cont.items()}}
    return out


def fetch_revisions(client: httpx.Client, revids: list[int]) -> dict[int, Revision]:
    result: dict[int, Revision] = {}
    for i in range(0, len(revids), 10):
        chunk = revids[i : i + 10]
        data = api_get(
            client,
            {
                "action": "query",
                "prop": "revisions",
                "revids": "|".join(map(str, chunk)),
                "rvslots": "main",
                "rvprop": "ids|content",
            },
        )
        query = data.get("query")
        if not isinstance(query, dict):
            continue
        for page in query.get("pages", []):
            for rev in page.get("revisions", []):
                text = rev.get("slots", {}).get("main", {}).get("content")
                if isinstance(text, str):
                    result[rev["revid"]] = {
                        "parentid": rev.get("parentid", 0),
                        "text": text,
                    }
    return result


def is_prose(paragraph: str) -> bool:
    stripped = paragraph.lstrip()
    if not stripped or stripped.startswith(NON_PROSE_START):
        return False
    plain = strip_wikitext(paragraph)
    return len(plain.split()) >= 5


def changed_paragraph(old_wikitext: str, new_wikitext: str) -> tuple[str, str] | None:
    """First 1:1 paragraph replacement where both sides are prose and change more than whitespace."""
    old_paras = old_wikitext.split("\n")
    new_paras = new_wikitext.split("\n")
    matcher = difflib.SequenceMatcher(None, old_paras, new_paras, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
            continue
        old_p, new_p = old_paras[i1], new_paras[j1]
        if not (is_prose(old_p) and is_prose(new_p)):
            continue
        old_plain, new_plain = (
            strip_wikitext(old_p).strip(),
            strip_wikitext(new_p).strip(),
        )
        if not (0 < len(old_plain) <= MAX_CHARS and 0 < len(new_plain) <= MAX_CHARS):
            continue
        if " ".join(old_plain.split()) == " ".join(new_plain.split()):
            continue
        # Line-level diffs can pair unrelated lines; require the two sides to be edits of each other.
        if difflib.SequenceMatcher(None, old_plain, new_plain).ratio() < MIN_SIMILARITY:
            continue
        return old_p, new_p
    return None


def build_case(
    case_id: str,
    rc: RecentChange,
    old_rev: int,
    new_rev: int,
    old_wt: str,
    new_wt: str,
    bucket: str,
    expected: str,
) -> tuple[Case, bool] | None:
    pair = changed_paragraph(old_wt, new_wt)
    if pair is None:
        return None
    old_p, new_p = pair
    ref_urls = extract_ref_urls(new_p)
    changed_ref_urls = refs_for_changed_sentences(old_p, new_p)
    case = Case(
        case_id=case_id,
        lang="en",
        bucket=bucket,
        provenance=f"https://en.wikipedia.org/w/index.php?diff={new_rev}&oldid={old_rev}",
        page_title=rc.title,
        old_text=strip_wikitext(old_p).strip(),
        new_text=strip_wikitext(new_p).strip(),
        ref_urls=ref_urls,
        old_wikitext=old_p,
        new_wikitext=new_p,
        changed_ref_urls=changed_ref_urls,
        expected=expected,
        notes=rc.comment,
    )
    return case, bool(changed_ref_urls)


def select(cands: list[Candidate], count: int = N_CASES) -> list[Candidate]:
    """Priority: POV with ref, other with ref, POV no-ref, other no-ref (no-ref capped)."""
    max_no_ref = int(count * MAX_NO_REF_SHARE)
    chosen: list[Candidate] = []
    no_ref = 0
    for pov, has_ref in [(True, True), (False, True), (True, False), (False, False)]:
        for c in cands:
            if len(chosen) >= count:
                return chosen
            if c.pov != pov or c.has_ref != has_ref:
                continue
            same_page = sum(x.case.page_title == c.case.page_title for x in chosen)
            if same_page >= MAX_PER_PAGE[c.case.bucket]:
                continue
            if not has_ref:
                if no_ref >= max_no_ref:
                    continue
                no_ref += 1
            chosen.append(c)
    return chosen


def collect_reverts(
    client: httpx.Client,
    rng: random.Random,
    count: int = N_CASES,
    exclude: frozenset[str] = frozenset(),
) -> list[Candidate]:
    rcs: dict[int, RecentChange] = {}
    for tag in ("mw-undo", "mw-rollback", "mw-manual-revert"):
        for rc in recent_changes(client, {"rctag": tag}, pages=6):
            rcs.setdefault(rc.revid, rc)
    pool = [
        rc
        for rc in rcs.values()
        if POV_RE.search(rc.comment) or WIDE_RE.search(rc.comment)
    ]
    pool.sort(key=lambda rc: not POV_RE.search(rc.comment))
    print(
        f"revert pool: {len(rcs)} reverts, {len(pool)} matching, {sum(bool(POV_RE.search(r.comment)) for r in pool)} POV"
    )
    cands: list[Candidate] = []
    for rc in pool[:300]:
        reverted = rc.old_revid
        if f"en_revert_{reverted}" in exclude:
            continue
        revs = fetch_revisions(client, [reverted])
        if reverted not in revs or not revs[reverted]["parentid"]:
            continue
        before = revs[reverted]["parentid"]
        before_rev = fetch_revisions(client, [before])
        if before not in before_rev:
            continue
        built = build_case(
            f"en_revert_{reverted}",
            rc,
            before,
            reverted,
            before_rev[before]["text"],
            revs[reverted]["text"],
            "en_revert",
            "UNLABELLED",
        )
        if built:
            cands.append(
                Candidate(
                    case=built[0], pov=bool(POV_RE.search(rc.comment)), has_ref=built[1]
                )
            )
        if len(cands) >= max(30, 2 * count):
            break
    rng.shuffle(cands)
    return cands


def collect_controls(
    client: httpx.Client,
    rng: random.Random,
    count: int = N_CASES,
    exclude: frozenset[str] = frozenset(),
) -> list[Candidate]:
    cutoff = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # rcdir=older with rcstart=cutoff walks backwards from 7 days ago.
    rcs = recent_changes(
        client,
        {"rcstart": cutoff, "rcdir": "older", "rcshow": "!bot|!minor|!redirect"},
        pages=2,
    )
    pool = [
        rc
        for rc in rcs
        if 30 <= abs(rc.sizediff) <= 600
        and not REVERT_WORDS_RE.search(rc.comment)
        and not POV_RE.search(rc.comment)
    ]
    rng.shuffle(pool)
    cands: list[Candidate] = []
    for rc in pool[:300]:
        if f"en_control_{rc.revid}" in exclude:
            continue
        revs = fetch_revisions(client, [rc.old_revid, rc.revid])
        if rc.old_revid not in revs or rc.revid not in revs:
            continue
        built = build_case(
            f"en_control_{rc.revid}",
            rc,
            rc.old_revid,
            rc.revid,
            revs[rc.old_revid]["text"],
            revs[rc.revid]["text"],
            "en_control",
            "CLEAN_PASS",
        )
        if built:
            print(f"  cand {len(cands)}", flush=True)
            cands.append(Candidate(case=built[0], pov=False, has_ref=built[1]))
        if len(cands) >= max(30, 2 * count):
            break
    return cands


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reverts", type=int, default=N_CASES)
    parser.add_argument("--controls", type=int, default=N_CASES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--exclude",
        type=Path,
        nargs="*",
        default=[],
        metavar="PATH",
        help="JSONL case files; any case_id found in them is skipped when collecting candidates",
    )
    parser.add_argument(
        "--controls-only",
        action="store_true",
        help="skip revert collection and do not overwrite en_reverts.jsonl",
    )
    parser.add_argument("--controls-out", type=Path, default=CONTROLS_PATH)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    exclude: frozenset[str] = frozenset(
        case.case_id for path in args.exclude for case in load_cases(path)
    )
    reverts: list[Candidate] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        if not args.controls_only:
            reverts = select(
                collect_reverts(client, rng, args.reverts, exclude), args.reverts
            )
        controls = select(
            collect_controls(client, rng, args.controls, exclude), args.controls
        )
    if not args.controls_only:
        dump_jsonl(REVERTS_PATH, [c.case for c in reverts])
    dump_jsonl(args.controls_out, [c.case for c in controls])
    if not args.controls_only:
        print(
            f"reverts: {len(reverts)} (POV {sum(c.pov for c in reverts)}, with ref {sum(c.has_ref for c in reverts)})"
        )
    print(f"controls: {len(controls)} (with ref {sum(c.has_ref for c in controls)})")


if __name__ == "__main__":
    main()
