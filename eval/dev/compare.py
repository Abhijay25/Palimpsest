"""Compare judge runs case by case: flags on clean controls, recall on should-flag reverts by cause."""
import json, sys
from collections import Counter, defaultdict
labels = json.load(open("eval/labels/g03_reverts_sonnet.json"))
ADMIN, REVIEW = 0.70, 0.45
def load(run):
    out = {}
    for line in open(f"eval/runs/{run}/results.jsonl"):
        r = json.loads(line)
        o = r.get("output") or {}
        v = o.get("verdict", "ERR"); c = o.get("confidence", 0.0)
        flag = v.startswith("FLAG")
        out[r["case_id"]] = (v, c, "admin" if flag and c >= ADMIN else "review" if flag and c >= REVIEW else "none" if not flag else "low")
    return out
runs = sys.argv[1:]
data = {r: load(r) for r in runs}
ids = sorted(set.intersection(*(set(d) for d in data.values())))
def bucket(cid):
    if "control" in cid: return "control"
    if cid.startswith("blp") or "silence" in cid: return "blp"
    return "revert"
print(f"{'group':38}" + "".join(f"{r[:22]:>24}" for r in runs))
groups = defaultdict(list)
for cid in ids:
    b = bucket(cid)
    if b == "revert":
        lab = labels.get(cid, {}); key = f"revert {lab.get('label','UNLABELLED')} ({'should' if lab.get('should_flag') else 'no-need'})"
    else: key = b + (" (en)" if cid.startswith("en") else " (fi)" if cid.startswith("fi") else "")
    groups[key].append(cid)
for key in sorted(groups):
    cells = []
    for r in runs:
        tiers = Counter(data[r][c][2] for c in groups[key])
        cells.append(f"adm{tiers['admin']}/rev{tiers['review']}/{len(groups[key])}")
    print(f"{key:38}" + "".join(f"{x:>24}" for x in cells))
diff = [c for c in ids if len({data[r][c][2] in ('admin','review') for r in runs}) > 1]
print(f"\ncases where flag decision differs: {len(diff)}")
for c in diff: print(" ", c, labels.get(c, {}).get("label", bucket(c)), " | ".join(f"{data[r][c][0]}@{data[r][c][1]:.2f}" for r in runs))
