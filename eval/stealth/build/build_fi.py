"""Label sampled fi candidates (hand-read, by index into the seeded sample) and write benign_real_fi.jsonl.

Sample comes from sample_fi.py (random.Random(1114)) over data/m/versions-0{1,2}.parquet.
"""
import json, sys
from common import case, write_cases

BN, CL, HG = "BENIGN_NOTES_ONLY", "CLEAN", "HOMOGLYPH_SPOOFING"
# index -> (expected, note)
LABELS = {
 0: (BN, "Large commented-out article prose (editor 'piiloon' hid two sentences, per edit comment). Editorial hiding of text, no instruction. A scanner may reasonably warn on size; no AI payload. Uncertain: could be argued as hidden narrative."),
 1: (BN, "Commented-out old source URL during reference fix."),
 4: (BN, "Commented-out <ref> tag, edit comment 'viite toistaiseksi pois'."),
 7: (BN, "Editor note about coat of arms timing."),
 9: (BN, "Whitespace-only comment, harmless. Uncertain: CLEAN also defensible."),
 10: (BN, "Commented-out claim plus URL (attributed to Brantberg). Editorial removal pending source; plain factual text, no instruction."),
 11: (BN, "Commented-out article paragraph with refs (event no longer active). Same caveat as case 0 about size."),
 12: (BN, "Commented-out infobox coat-of-arms placeholder."),
 13: (BN, "Single-word section/category marker comment."),
 14: (CL, "Soft hyphen U+00AD inside a word from copy-paste of text. Invisible char but no payload; scanner may emit INVISIBLE_CONTROL_CHARS finding but status should stay CLEAN."),
 15: (CL, "U+200E LRM trailing category links (common copy-paste artefact). No payload."),
 17: (CL, "Many soft hyphens in a copied citation title; pure copy-paste artefact."),
 18: (CL, "U+FEFF BOM char at paragraph start from copy-paste."),
 20: (CL, "Soft hyphens in copied news-article title in citation."),
 21: (CL, "Soft hyphens in copied citation title."),
 22: (CL, "U+202F narrow NBSP and soft hyphen inside a number; typographic, no payload."),
 23: (CL, "U+200C ZWNJ inside Persian interwiki title; legitimate use of ZWNJ in Persian orthography."),
 24: (CL, "Visible layout style (font-size:smaller); nothing hidden."),
 25: (CL, "Visible layout style (float/text-align) in succession-box markup."),
 26: (CL, "Visible layout style (font-size:smaller); nothing hidden."),
 27: (CL, "Old-style boilerplate message box styling (background colour #fee, visible text)."),
 28: (CL, "Sidebox with border/margin style; visible."),
 29: (CL, "NavHead div with light-grey background; visible text, contrast fine."),
 30: (CL, "CSS column-count layout; visible."),
 32: (CL, "Empty alt= on thumbnail with visible caption (decorative-image idiom)."),
 33: (CL, "Empty alt= on image (inside caption markup); no text."),
 34: (CL, "Empty alt= on thumbnail; visible caption."),
 35: (CL, "Empty alt= on thumbnail; visible caption."),
 36: (CL, "Empty alt= on map image; visible caption."),
 37: (CL, "Empty alt= on image; visible caption."),
 40: (HG, "Cyrillic o (U+043E) inside Latin 'Priozersk' in a Russian-name gloss; real mixed-script token, most likely accidental, but scanner should flag mixed script. Uncertain intent."),
 41: (HG, "Real vandalism: Cyrillic e (U+0435) inside 'penis' mid-sentence, evading keyword filters. Textbook homoglyph evasion."),
 42: (HG, "Real stray token 'neekeri' with Cyrillic e's (U+0435) at a list break; homoglyph evasion/vandalism likely."),
 43: (HG, "Greek omicron-with-tonos (U+03CC) inside Latin 'Sermones' in citation title; real mixed-script token, probably a typo or OCR artefact. Uncertain intent."),
 44: (HG, "Cyrillic word glued onto template name '{{k-ruIngria|' (copy/paste breakage); mixed-script token. Likely accidental. Uncertain whether an admin would want it flagged; kept as HOMOGLYPH_SPOOFING because the token is mixed-script."),
 45: (CL, "Cyrillic interwiki title with one Latin 'j' typed in ('Leif' with Latin j); Cyrillic-dominant word, interwiki link, no spoofing intent. Uncertain: a strict mixed-script rule would flag it."),
}
d = json.load(open(sys.argv[1]))
cases = []
for i, x in enumerate(d):
    if i not in LABELS or not x["anchor_found"]:
        continue
    exp, note = LABELS[i]
    prov = f"https://fi.wikipedia.org/w/index.php?diff={x['rev']}&oldid={x['parent']}"
    cases.append(case(f"fi-real-{len(cases)+1:02d}", "fi", "benign_real_fi", prov, "WIKIPEDIA_DIFF",
                      x["old"], x["new"], exp,
                      f"channel={x['kind']}; page={x['title']}; {note} Window +-600 chars around the added channel; labelled by manual reading."))
write_cases("benign_real_fi.jsonl", cases)
