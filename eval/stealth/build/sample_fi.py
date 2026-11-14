"""Seeded sample of fi candidates -> windows JSON for manual labelling."""
import difflib, json, pickle, random, re, sys
import pyarrow.parquet as pq

cands = pickle.load(open(sys.argv[1], "rb"))
rng = random.Random(1114)
QUOTA = {"comment": 14, "zw": 10, "style": 8, "alt": 8, "mixed": 6}
ZW = re.compile("[​-‏‪-‮⁦-⁩﻿⁠­]")
RX = {"comment": re.compile(r"<!--.*?-->", re.S), "style": re.compile(r"<(?:span|div)[^>]*style\s*=[^>]*>", re.I),
      "alt": re.compile(r"\balt\s*=[^|\]}]*", re.I), "zw": ZW}
pick = []
for k, q in QUOTA.items():
    pool = sorted([c for c in cands if c[0] == k], key=lambda c: c[1])
    seen, chosen = set(), []
    rng.shuffle(pool)
    for c in pool:
        if c[3] in seen: continue
        seen.add(c[3]); chosen.append(c)
        if len(chosen) == q: break
    pick += chosen
need = {c[1] for c in pick} | {c[2] for c in pick}
texts = {}
for f in ("01", "02"):
    pf = pq.ParquetFile(f"data/m/versions-{f}.parquet")
    for g in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(g, columns=["rev_id", "text", "comment", "user"]).to_pylist()
        for r in t:
            if r["rev_id"] in need: texts[r["rev_id"]] = r
out = []
for k, rev, par, title, ln in pick:
    new, old = texts[rev]["text"] or "", texts[par]["text"] or ""
    if k == "mixed":
        pos = None
        for m in re.finditer(r"\w+", new):
            w = m.group()
            if re.search("[A-Za-z]", w) and re.search("[Ѐ-ӿͰ-Ͽ]", w) and w not in old:
                pos = m.start(); break
        span = (pos, pos + 1) if pos is not None else None
    else:
        olds = [m.group() for m in RX[k].finditer(old)]
        span = None
        for m in RX[k].finditer(new):
            if m.group() in olds: olds.remove(m.group()); continue
            span = m.span(); break
    if k == "collapsible" or span is None: continue
    s, e = span
    nw = new[max(0, s - 600): e + 600]
    i, o_s = -1, min(s, len(old))
    for n_ctx in (60, 30, 15):
        anchor = new[max(0, s - n_ctx): s]
        if len(anchor) >= 15 and old.find(anchor) >= 0:
            i = old.find(anchor); o_s = i + len(anchor); break
    if i < 0:
        # Align the new-window to the old text via the longest common block.
        win0 = max(0, s - 600)
        sm = difflib.SequenceMatcher(None, old, new[win0: e + 600], autojunk=False)
        m = sm.find_longest_match(0, len(old), 0, e + 600 - win0)
        if m.size >= 40:
            o_s = m.a + (s - win0 - m.b); i = 0
    ow = old[max(0, o_s - 600): o_s + (e - s) + 600]
    out.append({"kind": k, "rev": rev, "parent": par, "title": title, "chan": new[s:e][:400], "edit_comment": texts[rev]["comment"],
                "user": texts[rev]["user"], "old": ow, "new": nw, "anchor_found": i >= 0})
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
print(len(out))
