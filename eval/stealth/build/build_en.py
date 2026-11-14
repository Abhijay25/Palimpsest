"""Build benign_real_en.jsonl from mine_en.py output (hand-labelled by index)."""

import difflib
import json
import re
import sys
from typing import TypedDict

from common import CaseRecord, case, write_cases

BN, CL = "BENIGN_NOTES_ONLY", "CLEAN"
RX = {
    "comment": re.compile(r"<!--.*?-->", re.DOTALL),
    "style": re.compile(r"style\s*=\s*\"[^\"]*\"", re.IGNORECASE),
    "alt": re.compile(r"\balt\s*=[^|\]}]*", re.IGNORECASE),
}
LABELS = {
    0: (CL, "Table cell style=text-align:center; visible layout."),
    1: (
        CL,
        "Table row background colour style (championship table); visible text with legible contrast.",
    ),
    2: (
        CL,
        "Descriptive alt text matching the caption ('Portrait of Charles Ferster'); legitimate accessibility alt.",
    ),
    3: (CL, "wikitable font-size:87%; visible layout."),
    4: (BN, "Short editor note comment 'Original airings only' in infobox."),
    5: (
        BN,
        "Short field-label comments such as '<!-- Commanders -->' in an infobox rewrite; benign editorial notes. Uncertain: parent revision is years older so the diff is large.",
    ),
    6: (
        BN,
        "Commented-out infobox fields (office/predecessor) with WP:CRYSTAL rationale; factual, no instruction.",
    ),
    7: (
        CL,
        "Table cell styling (padding, alignment, white background colour with default dark text); visible layout, not cloaking.",
    ),
    8: (CL, "Chart table style=text-align:center; visible layout."),
}


class MinedRevision(TypedDict):
    title: str
    rev: int
    parent: int
    kinds: list[str]
    comment: str
    added: str
    old: str
    new: str


with open(sys.argv[1]) as fh:
    d: list[MinedRevision] = json.load(fh)
cases: list[CaseRecord] = []
for i, x in enumerate(d):
    k = x["kinds"][0]
    new, old = x["new"], x["old"]
    span = None
    for m in RX[k].finditer(new):
        if m.group().strip() and m.group() in x["added"]:
            span = m.span()
            break
    if span is None:
        continue
    s, e = span
    win0 = max(0, s - 600)
    nw = new[win0 : e + 600]
    sm = difflib.SequenceMatcher(None, old, nw, autojunk=False)
    common_block = sm.find_longest_match(0, len(old), 0, len(nw))
    o_s = (
        common_block.a - common_block.b + (s - win0)
        if common_block.size >= 40
        else min(s, len(old))
    )
    ow = old[max(0, o_s - 600) : o_s + (e - s) + 600]
    if ow == nw:
        continue  # channel already present in parent; not an addition
    exp, note = LABELS[i]
    prov = f"https://en.wikipedia.org/w/index.php?diff={x['rev']}&oldid={x['parent']}"
    cases.append(
        case(
            f"en-real-{len(cases) + 1:02d}",
            "en",
            "benign_real_en",
            prov,
            "WIKIPEDIA_DIFF",
            ow,
            nw,
            exp,
            f"channel={k}; page={x['title']}; {note} Window +-600 chars around added channel; found via recentchanges 2026-11; labelled by manual reading.",
        )
    )
write_cases("benign_real_en.jsonl", cases)
