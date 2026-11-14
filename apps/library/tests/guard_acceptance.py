"""Real reader guard checks. No response content is fabricated or seeded.

Generated-text refusal uses a browser Range over an actual transclusion; native
mouse gestures are covered separately. The race delays an unchanged real HTTP
response, without changing the app's CSP or the producer's result.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.async_api import async_playwright, expect, Error as PlaywrightError

ORIGIN = os.environ['LIBRARY_BROWSER_ORIGIN'].rstrip('/')
EVIDENCE = Path(os.environ.get('LIBRARY_BROWSER_EVIDENCE', '/evidence'))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800}, reduced_motion='reduce')
        page = await context.new_page()
        errors, analyses = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def record_request(request):
            params = parse_qs(urlparse(request.url).query)
            if params.get('op') == ['analyze']:
                analyses.append(request.url)

        page.on('request', record_request)
        # Validate the ordinary production payload before exercising its limit.
        params = {'action': 'palimpsestblame', 'op': 'analyze',
                  'title': 'Pyöreä torni', 'revision': '59',
                  'ranges': json.dumps([{'start': 311, 'end': 347}])}
        ordinary_response = await context.request.get(ORIGIN+'/api/wiki/fi', params=params)
        assert ordinary_response.status == 200
        ordinary_payload = (await ordinary_response.json())['palimpsestblame']
        assert ordinary_payload['status'] == 'ready'
        assert ordinary_payload['snapshot']['revision_id'] == 59
        source = ordinary_payload['source_text'].encode('utf-16-le')
        assert source[622:694].decode('utf-16-le') == 'Torni rakennettiin vuosina 1547–1550'
        params['ranges'] = json.dumps([{'start': 311, 'end': 347}]*65)
        over_limit = await context.request.get(ORIGIN+'/api/wiki/fi', params=params)
        assert over_limit.status == 200
        limit_payload = (await over_limit.json())['palimpsestblame']
        assert limit_payload['status'] == 'unavailable'
        assert limit_payload['reason'] == 'selection-range-limit-exceeded'
        assert 'source_text' not in limit_payload and 'selection' not in limit_payload
        await page.goto(ORIGIN+'/#topic=Q110908561&lang=en&view=reader&revision=37')
        frame = page.frame_locator('iframe')
        root = frame.locator('#palimpsest-blame')
        await expect(root).to_have_attribute('data-state', 'ready')
        ordinary = frame.locator('.mw-parser-output .pb-attributed[role="button"]').first
        await expect(ordinary).to_have_text('Luntoberget')
        await ordinary.press('Enter')
        await expect(frame.locator('.pb-selected-text')).to_have_text('Luntoberget')
        await expect(frame.locator('.pb-revision-group')).to_have_count(1)
        await page.keyboard.press('Escape')
        await expect(frame.locator('.pb-breakdown')).to_have_count(0)

        generated = frame.locator('.mw-parser-output a[typeof~="mw:Transclusion"]').filter(has_text='Template:Cite web').first
        await expect(generated).to_be_attached()
        before = len(analyses)
        await generated.evaluate('''node => {
            node.scrollIntoView({block:'center'});
            const range=document.createRange(); range.selectNodeContents(node);
            const selection=window.getSelection();
            selection.removeAllRanges(); selection.addRange(range);
        }''')
        await frame.locator('.reader-inspect').click()
        await expect(root).to_have_attribute('data-state', 'incomplete')
        warning = frame.locator('.pb-selection-incomplete')
        # This fixture is wholly unmapped, so it takes the zero-source-offset
        # guard; mixed mapped/generated selections use a different native message.
        await expect(warning).to_contain_text('no verified source offsets')
        await expect(frame.locator('.pb-selected-text')).to_have_text('Template:Cite web')
        await expect(frame.locator('.pb-revision-group')).to_have_count(0)
        assert len(analyses) == before, 'Generated selection must not request partial attribution'
        refusal = {'case': 'actual generated text refused',
                   'selectionMethod': 'Browser Range; gesture acceptance is separate',
                   'quote': await frame.locator('.pb-selected-text').inner_text(),
                   'warning': await warning.inner_text(),
                   'analysisRequestsBefore': before,
                   'analysisRequestsAfter': len(analyses)}

        started, released = asyncio.Event(), asyncio.Event()
        delayed = {}

        async def hold_swedish(route):
            response = await route.fetch()
            payload = await response.json()
            assert response.status == 200
            assert payload['language'] == 'sv' and len(payload['versions']) == 12
            delayed['actualResponseLanguage'] = payload['language']
            delayed['actualRevisionCount'] = len(payload['versions'])
            started.set()
            await asyncio.sleep(1.5)
            try:
                await route.fulfill(response=response)
                delayed['delivery'] = 'released unchanged'
            except PlaywrightError as error:
                # AbortController may cancel the superseded request before release.
                delayed['delivery'] = 'request cancelled before release'
                delayed['failure'] = route.request.failure
                delayed['deliveryError'] = str(error)
            finally:
                released.set()

        await page.route('**/api/topics/Q110908561/revisions?lang=sv', hold_swedish)
        dialog = page.get_by_role('dialog')
        await dialog.get_by_role('button', name='Svenska', exact=True).press('Enter')
        await asyncio.wait_for(started.wait(), timeout=10)
        await dialog.get_by_role('button', name='Suomi', exact=True).press('Enter')
        await expect(page.locator('iframe')).to_have_attribute('src', '/reader/Q110908561/fi/67')
        await expect(frame.locator('#palimpsest-blame')).to_have_attribute('data-state', 'ready')
        await asyncio.wait_for(released.wait(), timeout=10)
        assert delayed['delivery'] == 'released unchanged' or 'ERR_ABORTED' in (delayed.get('failure') or ''), delayed
        await expect(page.locator('iframe')).to_have_attribute('src', '/reader/Q110908561/fi/67')
        await expect(page.locator('.book-heading p')).to_have_text('4 Jul 2024 UTC · revision 67')
        await expect(page.locator('.sr-only')).to_contain_text('Language changed to Suomi')
        await expect(frame.locator('.pb-breakdown')).to_have_count(0)
        assert not errors, errors
        result = {'passed': True, 'selectionLimit': limit_payload, 'generated': refusal,
                  'staleLanguageResponse': {**delayed, 'finalReader': '/reader/Q110908561/fi/67',
                                            'finalLabel': await page.locator('.book-heading p').inner_text()},
                  'pageErrors': errors}
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE/'reader-guards.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result, indent=2))
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
