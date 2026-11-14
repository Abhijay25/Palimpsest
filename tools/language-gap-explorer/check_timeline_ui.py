"""Offline browser contract/layout test. Synthetic fixtures; NOT a live backtest.

No listening server, DB, downloads, translations or paid calls. Routes use Flask's
test client so actual templates, assets, JS filters and fragment requests execute.
"""
import copy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from app import app
from test_semantic_timeline import fixture
import semantic_timeline as timeline


def main():
    rows=[]
    for i,lang in enumerate(timeline.LANGUAGES):
        row=fixture(lang);row['id']=str(i+1)*64;row['stamp']=f'2025-07-{i+1:02d}T12:00:00Z'
        rows.append(row)
    client=app.test_client();errors=[];requests=[]

    def route_handler(route):
        parsed=urlsplit(route.request.url)
        target=parsed.path+('?' + parsed.query if parsed.query else '')
        requests.append(target)
        if target.startswith('/translations'):
            route.fulfill(status=503,content_type='application/json',body='{"error":"Offline browser fixture: translation unavailable."}')
            return
        response=client.open(target,method=route.request.method,data=route.request.post_data,
            content_type=route.request.headers.get('content-type'))
        route.fulfill(status=response.status_code,body=response.get_data(),
            content_type=response.content_type)

    with patch.object(timeline,'overview',side_effect=lambda:(copy.deepcopy(rows),None)),patch.object(timeline,'editions',return_value={}),patch.object(timeline,'cached_revision',return_value=None),patch.object(timeline,'api',side_effect=AssertionError('Browser read fetched external data')),patch('live_api.decisions',side_effect=AssertionError('Browser spent')):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/*',route_handler)
            page.goto('http://timeline.test/wiki/Q134949/timeline?lang=en',wait_until='networkidle')
            expect(page.get_by_role('heading',name='When did the story change?')).to_be_visible()
            assert page.locator('.showcase-tabs a').count()==4
            assert page.locator('.timeline-edit').count()==4
            assert page.locator('.tl-marker').count()==4
            page.locator('input[name=edition][value=ru]').uncheck()
            assert page.locator('.timeline-edit').count()==3
            page.locator('input[name=edition][value=ru]').check()
            page.locator('input[name=from]').fill('2025-07-03')
            page.locator('input[name=from]').dispatch_event('change')
            assert page.locator('.timeline-edit').count()==2
            page.get_by_role('button',name='Reset dates').click()
            page.locator('.timeline-event-link').nth(1).click()
            expect(page.locator('.timeline-event-detail')).to_be_visible()
            assert page.locator('.timeline-current h4').inner_text()=='Your article · English'
            assert page.locator('.timeline-changed h4').inner_text()=='Changed article · Finnish'
            assert page.locator('.timeline-current').evaluate('(el)=>el.compareDocumentPosition(document.querySelector(".timeline-changed")) & Node.DOCUMENT_POSITION_FOLLOWING')
            assert page.locator('del').count()>0 and page.locator('ins').count()>0
            expect(page.get_by_role('link',name='Open full Wikipedia diff')).to_be_visible()
            assert page.locator('.translation-output').count()==2
            page.locator('body').click(position=dict(x=5,y=5))
            output=Path('reports');output.mkdir(exist_ok=True)
            page.screenshot(path=str(output/'winter-war-timeline-desktop.png'),full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            page.screenshot(path=str(output/'winter-war-timeline-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('.showcase-tabs a:visible').count()==4
            page.locator('.timeline-event-link').first.click()
            expect(page.locator('.timeline-local')).to_be_visible()
            assert page.locator('.timeline-current').count()==0
            assert not any('/compare?' in r for r in requests)
            assert not errors,errors
            browser.close()
    print('Offline timeline browser checks passed: four lanes/tabs, filters, exact diff, original/translation panels, ours-left, local edit, desktop/mobile, no fetch/spend.')


if __name__=='__main__':main()
