"""Optional local browser regression for prepared real data; never requests enrichment.

This script requires a populated paired_history run and the preview on port 8020.
It is not a model accuracy evaluation or a substitute for source validation.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright,expect


def main():
    output=Path('reports/discrepancy-explorer');output.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8020/explore')
        expect(page.locator('#topic-search')).to_have_value('')
        page.screenshot(path=str(output/'prompt-desktop.png'))
        page.locator('[data-example=Q134949]').click()
        expect(page.locator('#graph-screen')).to_be_visible(timeout=20000)
        expect(page.locator('.chart-row').first).to_be_visible(timeout=20000)
        assert page.locator('.chart-row').count()>6
        page.locator('.row-label').first.click()
        page.get_by_role('button',name='Read the evidence',exact=True).click()
        expect(page.locator('#occurrence-select')).to_be_visible(timeout=20000)
        expect(page.locator('.evidence-card blockquote').first).to_be_visible()
        assert page.locator('.evidence-card a').first.get_attribute('href').startswith('https://')
        page.screenshot(path=str(output/'real-evidence.png'))
        page.get_by_role('button',name='Close evidence',exact=True).click()
        page.get_by_role('button',name='Close interval details',exact=True).click()
        for _ in range(22):page.get_by_role('button',name='Zoom in',exact=True).click()
        start=float(page.locator('#window-start').input_value());end=float(page.locator('#window-end').input_value())
        step=float(page.locator('#window-start').get_attribute('step'))
        assert end-start>=step-.001
        page.get_by_role('button',name='Reset time window',exact=True).click()
        page.screenshot(path=str(output/'real-graph-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(output/'real-graph-mobile.png'))
        assert not errors,errors
        browser.close()
    print('Prepared real-data browser checks passed. No enrichment or inference started.')


if __name__=='__main__':main()
