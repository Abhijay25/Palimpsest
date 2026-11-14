"""Mine candidate hidden-channel additions from fi versions parquet; dumps candidates to a pickle."""

import pickle, re, sys, unicodedata
import pyarrow.parquet as pq

OUT = sys.argv[1]
ZW = re.compile("[​-‏‪-‮⁦-⁩﻿⁠­]")
chan = {
    "comment": re.compile(r"<!--.*?-->", re.S),
    "style": re.compile(r"<(?:span|div)[^>]*style\s*=", re.I),
    "alt": re.compile(r"\balt\s*=", re.I),
    "collapsible": re.compile(r"mw-collapsible", re.I),
    "zw": ZW,
}


def mixed(t):
    out = set()
    for w in re.findall(r"\w+", t):
        if re.search("[A-Za-z]", w) and re.search("[Ѐ-ӿͰ-Ͽ]", w):
            out.add(w)
    return out


feat = {}  # rev_id -> (page_id, parent_id, title, counts, mixed)
for f in ("01", "02"):
    pf = pq.ParquetFile(f"data/m/versions-{f}.parquet")
    for g in range(pf.metadata.num_row_groups):
        for r in pf.read_row_group(g).to_pylist():
            t = r["text"] or ""
            feat[r["rev_id"]] = (
                r["page_id"],
                r["parent_id"],
                r["title"],
                {k: len(rx.findall(t)) for k, rx in chan.items()},
                mixed(t),
                len(t),
            )
print(len(feat), flush=True)
cands = []
for rev, (pid, par, title, cnt, mx, ln) in feat.items():
    p = feat.get(par)
    if not p or p[0] != pid:
        continue
    for k in chan:
        if cnt[k] > p[3][k]:
            cands.append((k, rev, par, title, ln))
    if mx - p[4]:
        cands.append(("mixed", rev, par, title, ln))
from collections import Counter

print(Counter(c[0] for c in cands))
pickle.dump(cands, open(OUT, "wb"))
