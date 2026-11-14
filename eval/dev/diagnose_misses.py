"""Fan out one Gemini call per missed edit: was the problem catchable from the edit itself?"""
import asyncio, difflib, json, os, sys
from collections import Counter
from google import genai
from google.genai import types
from pydantic import BaseModel

class Verdict(BaseModel):
    catchable_from_edit: bool
    category: str  # FACTUAL_SWAP | UNSOURCED_CLAIM | POV_WORDING | VANDALISM_OR_TEST | REMOVED_CONTENT | STYLE_FORMAT | NOTABILITY_POLICY | DISPUTE_OR_PREFERENCE | REFINEMENT | OTHER
    what_was_wrong: str
    which_check_should_catch: str

SYSTEM = ("You are reviewing why an automated Wikipedia edit reviewer did NOT flag an edit that a later human editor reverted or corrected. "
          "Decide whether the problem the later editor fixed could reasonably be spotted from the edit itself (its added/changed text and its citations), "
          "without knowing the future. Reverts for notability, formatting, house style, editor disputes or preference are NOT catchable. "
          "category: FACTUAL_SWAP, UNSOURCED_CLAIM, POV_WORDING, VANDALISM_OR_TEST, REMOVED_CONTENT, STYLE_FORMAT, NOTABILITY_POLICY, DISPUTE_OR_PREFERENCE, REFINEMENT (later edit just improved wording/accuracy slightly), OTHER. "
          "what_was_wrong: one plain-English sentence. which_check_should_catch: one short phrase (e.g. 'value check against source', 'wording policy', 'vandalism detection', 'none').")

def changed(old: str, new: str, limit: int = 3500) -> str:
    a, b = old.split("\n\n"), new.split("\n\n")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal": continue
        out.append("OLD:\n" + "\n\n".join(a[i1:i2])[:1200] + "\nNEW:\n" + "\n\n".join(b[j1:j2])[:1200])
    return "\n---\n".join(out)[:limit]

async def main() -> None:
    rows = {(r["lang"], r["rev_id"]): r for r in json.load(open(sys.argv[1]))}
    edits = [json.loads(l) for f in sys.argv[3:] for l in open(f)]
    misses = [e for e in edits if e["label"] in ("reverted", "corrected") and rows[(e["lang"], e["rev_id"])]["flagged"] == "none"]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"]); sem = asyncio.Semaphore(8); results = []
    async def one(e: dict) -> None:
        payload = json.dumps({"language": e["lang"], "page": e["page_title"], "edit_summary": e.get("comment"), "ground_truth": e["label"],
            "later_edit_summary": e.get("later_comment"), "what_later_changed": e.get("changed_by_later"), "edit_diff": changed(e["old_wikitext"], e["new_wikitext"])}, ensure_ascii=False)
        async with sem:
            r = await client.aio.models.generate_content(model=sys.argv[2], contents=payload, config=types.GenerateContentConfig(
                system_instruction=SYSTEM, response_mime_type="application/json", response_schema=Verdict, temperature=0, seed=7,
                thinking_config=types.ThinkingConfig(thinking_level="low")))
        v = Verdict.model_validate_json(r.text)
        results.append({"lang": e["lang"], "page": e["page_title"], "rev_id": e["rev_id"], "label": e["label"], **v.model_dump()})
    await asyncio.gather(*(one(e) for e in misses))
    json.dump(results, open(sys.argv[1].replace("rows.json", "misses.json"), "w"), ensure_ascii=False, indent=1)
    print("misses:", len(results), "catchable:", sum(r["catchable_from_edit"] for r in results))
    print(Counter((r["label"], r["category"], r["catchable_from_edit"]) for r in results).most_common(20))
asyncio.run(main())
