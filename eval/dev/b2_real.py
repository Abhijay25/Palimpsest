import json, sys, time, urllib.request
from collections import Counter
for path in sys.argv[1:]:
    tally = Counter(); n = 0
    for line in open(path):
        c = json.loads(line); n += 1
        o, nw = c["old_wikitext"], c["new_wikitext"]
        body = {"lang_code": c.get("lang", "en"), "page_title": c["page_title"], "old_revision_id": 0, "new_revision_id": 0, "editor_username": "eval", "old_text": o, "new_text": nw, "old_wikitext": o, "new_wikitext": nw, "ref_urls": c.get("ref_urls") or []}
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8765/api/v1/audit-diff", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=180))
        except Exception as e:
            tally["error"] += 1; continue
        kinds = {(f["kind"], f["tier"]) for f in r["flags"]}
        cp = (r.get("cherry_pick") or {}).get("status")
        tally[f"b2_{cp}"] += 1
        if any(k == "CHERRY_PICK" for k, _ in kinds): tally["b2_flag"] += 1
        if any(t == "admin" for _, t in kinds): tally["any_admin"] += 1
        elif kinds: tally["any_review_only"] += 1
        print(c["page_title"][:30], c.get("bad_rev_id"), sorted(kinds), "b2:", cp, flush=True)
    print("==", path, n, dict(tally), flush=True)
