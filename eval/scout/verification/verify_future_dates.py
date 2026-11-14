"""Run the citation-date check on the isolated scout's real future-date cases."""
import asyncio, json, re, sys
from datetime import UTC, datetime
import httpx
from palimpsest.citation_dates import scan_changed_citation_dates
from palimpsest.crosslingual import MEDIAWIKI_USER_AGENT

async def main() -> None:
    cases = [json.loads(l) for l in open(sys.argv[1])]
    hits = 0
    async with httpx.AsyncClient(headers={"User-Agent": MEDIAWIKI_USER_AGENT}, timeout=20) as client:
        for c in cases:
            r = await client.get(f"https://{c['lang']}.wikipedia.org/w/api.php", params={"action": "query", "prop": "revisions", "revids": str(c["revid"]), "rvprop": "content|timestamp", "rvslots": "main", "format": "json", "formatversion": "2"})
            page = r.json()["query"]["pages"][0]["revisions"][0]
            wt, ts = page["slots"]["main"]["content"], page["timestamp"]
            key = c["wikitext_snippet"].strip()[:60]
            pos = wt.find(key) if key in wt else wt.find(c["wikitext_snippet"].strip()[-60:])
            r0 = wt.rfind("<ref", 0, pos + 1); start = r0 if r0 >= 0 and wt.find("</ref>", r0) >= pos else max(wt.rfind("\n", 0, pos + 1), 0)
            end = wt.find("</ref>", pos) + 6 if pos >= 0 and wt.find("</ref>", pos) > 0 else pos + 600
            unit = wt[start:end] if pos >= 0 else ""
            scan = await scan_changed_citation_dates(c["lang"], c["title"], [unit] if unit else [], client=client, now=datetime.fromisoformat(ts.replace("Z", "+00:00")))
            found = [f for f in scan.findings if f.code == "FUTURE_DATE"]
            ok = any(f.parsed_date.isoformat()[:7] == c["rendered_date"][:7] or c["rendered_date"] in f.rendered_date for f in found) or bool(found)
            hits += ok
            print(f"{'HIT ' if ok else 'MISS'} {c['lang']} {c['title'][:34]:34} rendered={c['rendered_date']:12} status={scan.status} found={[f.rendered_date for f in found][:3]} unit_chars={len(unit)} err={scan.error and scan.error[:80]}")
            await asyncio.sleep(1.0)
    print(f"\nfuture dates caught: {hits}/{len(cases)}")
asyncio.run(main())
