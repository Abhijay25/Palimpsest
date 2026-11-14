"""Mine English Wikipedia recent edits that add hidden channels; writes benign_real_en candidates JSON."""
import json, re, sys, time
import urllib.parse, urllib.request, urllib.error

API = "https://en.wikipedia.org/w/api.php"
HDR = {"User-Agent": "Palimpsest-MVP/0.1 (hackathon research)"}
MAX_REQ, TARGET = 150, 24
n_req = 0


def call(params):
    global n_req
    params = {**params, "format": "json", "maxlag": 5}
    for _ in range(5):
        time.sleep(1.1); n_req += 1
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=HDR)
        try:
            data = json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(15); continue
            raise
        if data.get("error", {}).get("code") == "maxlag":
            time.sleep(10); continue
        return data
    raise RuntimeError("retries exhausted")


CH = {"comment": re.compile(r"<!--"), "style": re.compile(r"style\s*=", re.I),
      "alt": re.compile(r"\balt\s*=", re.I), "collapsible": re.compile(r"mw-collapsible", re.I)}
out, seen_pages = [], set()
cont = {}
while len(out) < TARGET and n_req < MAX_REQ:
    rc = call({"action": "query", "list": "recentchanges", "rcnamespace": 0, "rctype": "edit",
               "rcprop": "ids|title|comment|sizes", "rclimit": 100, "rcshow": "!bot", **cont})
    cont = rc.get("continue", {})
    for ch in rc["query"]["recentchanges"]:
        if len(out) >= TARGET or n_req >= MAX_REQ - 3:
            break
        if not ch["old_revid"] or ch["title"] in seen_pages or abs(ch["newlen"] - ch["oldlen"]) > 3000:
            continue
        cmp_ = call({"action": "compare", "fromrev": ch["old_revid"], "torev": ch["revid"], "prop": "diff"})
        diff = cmp_.get("compare", {}).get("*", "")
        added = re.findall(r'<ins class="diffchange[^>]*>(.*?)</ins>|<td class="diff-addedline[^>]*>(.*?)</td>', diff, re.S)
        added = " ".join(a or b for a, b in added)
        import html
        added = html.unescape(re.sub(r"<[^>]+>", "", added))
        kinds = [k for k, rx in CH.items() if rx.search(added)]
        if not kinds:
            continue
        revs = call({"action": "query", "prop": "revisions", "rvprop": "ids|content", "rvslots": "main",
                     "revids": f"{ch['old_revid']}|{ch['revid']}"})
        texts = {}
        for pg in revs["query"]["pages"].values():
            for rv in pg["revisions"]:
                texts[rv["revid"]] = rv["slots"]["main"]["*"]
        out.append({"title": ch["title"], "rev": ch["revid"], "parent": ch["old_revid"], "kinds": kinds,
                    "comment": ch["comment"], "added": added[:1500], "old": texts[ch["old_revid"]], "new": texts[ch["revid"]]})
        seen_pages.add(ch["title"])
        print(len(out), n_req, ch["title"], kinds, flush=True)
    if not cont:
        break
json.dump(out, open(sys.argv[1], "w"))
print("done", len(out), n_req)
