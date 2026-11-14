import json, sys, time
from playwright.sync_api import sync_playwright
S = sys.argv[1]
pairs = json.load(open(f"{S}/mwlite/pairs.json"))
only = sys.argv[2:] 
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/etc/profiles/per-user/abhijay/bin/chromium", args=["--disable-gpu", "--renderer-process-limit=1"])
    pg = b.new_page(viewport={"width": int(__import__("os").environ.get("VW", "1440")), "height": 1000}, color_scheme=__import__("os").environ.get("SCHEME", "light"))
    errs = []
    pg.on("console", lambda m: errs.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    for i, pr in enumerate(pairs):
        if only and pr["title"] not in only: continue
        t = time.time()
        pg.goto(f"http://127.0.0.1:8090/index.php?title={pr['title'].replace(' ', '_')}&diff={pr['new']}&oldid={pr['old']}")
        try:
            pg.wait_for_function("() => document.querySelector('.pf-card') || /No issues|unavailable|Audit/i.test((document.querySelector('.pf-summary-bar')||{}).innerText||'')", timeout=90000)
        except Exception as e:
            errs.append(f"{pr['title']}: wait failed {e}")
        pg.wait_for_timeout(600)
        bar = pg.locator(".pf-summary-bar").first
        print(pr["title"], f"{time.time()-t:.1f}s", "cards=", pg.locator(".pf-card").count(), "marks=", pg.locator("mark.pf-anchor").count(), "bar=", (bar.inner_text()[:120].replace("\n", " | ") if bar.count() else None))
        pg.screenshot(path=f"{S}/shots/{i}_{pr['title'].replace(' ', '_')}.png")
        if True:
            card = pg.locator(".pf-card").first
            if card.count():
                card.hover(); pg.wait_for_timeout(400); pg.screenshot(path=f"{S}/shots/{i}_hover.png")
                card.locator(".pf-card__toggle, button").first.click(); pg.wait_for_timeout(600); pg.screenshot(path=f"{S}/shots/{i}_expanded.png")
    print("console:", *errs[:15], sep="\n  ")
    b.close()
