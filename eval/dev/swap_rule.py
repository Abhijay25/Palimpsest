"""Offline what-if: deterministic value-swap detection + judge's own UNSUPPORTED marks -> review tier."""
import json, re, sys, difflib
from collections import Counter
run = sys.argv[1]
labels = json.load(open("eval/labels/g03_reverts_sonnet.json"))
prep = {json.loads(l)["case"]["case_id"]: json.loads(l)["case"] for l in open(f"eval/runs/{run}/prepared.jsonl")}
res = {json.loads(l)["case_id"]: json.loads(l) for l in open(f"eval/runs/{run}/results.jsonl")}
TOK = re.compile(r"\d[\d.,]*|[A-ZÅÄÖ][\w'-]+(?:\s[A-ZÅÄÖ][\w'-]+)*")
def _norm(v: str) -> str:
    v = v.strip("()[]{}\"'“”«»|=").rstrip(".,;:")
    return re.sub(r"['’]s$", "", v)
def _values(words):
    """Numbers anywhere; capitalised words only when not sentence-initial."""
    vals = set()
    for k, w in enumerate(words):
        w2 = _norm(w)
        if re.fullmatch(r"\d[\d.,]*", w2): vals.add(w2.rstrip(".,"))
        elif w2[:1].isupper() and k > 0 and not words[k-1].endswith((".", "!", "?")): vals.add(w2)
    return vals
def _same(o: str, n: str) -> bool:
    """Same value: inflection/extension (shared prefix) or a small spelling fix of a word."""
    if o.isdigit() or n.isdigit() or any(ch.isdigit() for ch in o + n): return o == n
    if n.startswith(o) or o.startswith(n): return True
    k = 0
    while k < min(len(o), len(n)) and o[k] == n[k]: k += 1
    if k >= 4 and k >= 0.6 * min(len(o), len(n)): return True
    return len(o) == len(n) and sorted(o) == sorted(n) or difflib.SequenceMatcher(None, o, n).ratio() >= 0.8
def swaps(a: str, b: str):
    """Values present in a replaced span on both sides (an existing value replaced by another)."""
    out = []
    ta, tb = a.split(), b.split()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op != "replace": continue
        ctx_a = ta[max(0, i1-1):i2]; ctx_b = tb[max(0, j1-1):j2]
        old_v = _values(ctx_a)[1:] if False else _values(ctx_a) - _values(ta[max(0,i1-1):i1])
        new_v = _values(ctx_b) - _values(tb[max(0,j1-1):j1])
        gone = {o for o in old_v if not any(_same(o, n) for n in new_v) and o not in b}
        came = {n for n in new_v if not any(_same(o, n) for o in old_v) and n not in a}
        isnum = lambda v: v[:1].isdigit()
        for kind in (True, False):
            g = {v for v in gone if isnum(v) == kind}; c = {v for v in came if isnum(v) == kind}
            if g and c: out.append((g, c))
    return [s for s in out if s[0] and s[1]]
def rule(cid):
    r = res[cid]; o = r.get("output") or {}
    if (o.get("verdict") or "").startswith("FLAG"): return "already"
    c = prep[cid]; sw = swaps(c["old_text"], c["new_text"])
    if not sw: return "no"
    new_vals = set().union(*(n for _, n in sw))
    for p in o.get("atomic_propositions") or []:
        if p.get("source_entailment") in ("UNSUPPORTED_EXTRAPOLATION", "CONTRADICTED") and any(v in p.get("clause_text", "") for v in new_vals):
            return "review"
    return "no"
groups = {}
for cid in res:
    if cid not in prep: continue
    if "control" in cid: g = "control " + cid[:2]
    elif cid.startswith("blp"): continue
    else:
        lab = labels.get(cid, {}); g = f"revert {lab.get('label')} ({'should' if lab.get('should_flag') else 'no-need'})"
    groups.setdefault(g, Counter())[rule(cid)] += 1
for g in sorted(groups): print(f"{g:42} {dict(groups[g])}")
if len(sys.argv) > 2:
    for cid in res:
        if cid in prep and rule(cid) == "review" and ("control" in cid or labels.get(cid, {}).get("should_flag")):
            c = prep[cid]; print("==", cid, labels.get(cid, {}).get("label", "CONTROL"), res[cid].get("source_status"))
            for o_, n_ in swaps(c["old_text"], c["new_text"]): print("   ", sorted(o_)[:4], "->", sorted(n_)[:4])
