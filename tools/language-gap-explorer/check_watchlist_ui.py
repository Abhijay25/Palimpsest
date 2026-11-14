from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from test_watchlist import WatchlistTests
from core import connect

fixture=WatchlistTests(methodName='test_link_confirmation_is_idempotent')
fixture.setUpClass();fixture.setUp()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8010/watchlist?topic=Q2606233',wait_until='networkidle')
        expect(page.locator('.watch-notice').first).to_be_visible()
        expect(page.locator('.local-translation').first.locator('.translation-output')).not_to_contain_text('Loading',timeout=60000)
        expect(page.locator('.local-translation').first.locator('.translation-output')).not_to_contain_text('Translating',timeout=60000)
        assert 'unavailable' not in page.locator('.translation-output').first.inner_text().lower()
        page.screenshot(path='screenshots/watchlist-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.get_by_role('link',name='Link passages',exact=True)).to_be_visible()
        page.screenshot(path='screenshots/watchlist-mobile.png',full_page=True)
        page.set_viewport_size({'width':1440,'height':1100})
        page.goto('http://127.0.0.1:8010/watchlist/new?topic='+fixture.topic)
        page.locator('#quote').fill(fixture.quotes['en'])
        page.get_by_role('button',name='Find semantic counterparts locally').click()
        expect(page.locator('.watch-candidate')).to_have_count(2,timeout=60000)
        # One paragraph matches the population statement; the other is unrelated.
        candidates=page.locator('.watch-candidate').filter(has_text='1000 asukasta')
        candidates.first.locator('input[type=checkbox]').check()
        page.locator('#link-title').fill('Population in 2020')
        page.locator('#link-note').fill('Same population measure and year, confirmed in browser test.')
        page.locator('input[name=confirmed]').check()
        page.get_by_role('button',name='Confirm link and start watching').click()
        expect(page).to_have_url('http://127.0.0.1:8010/watchlist/links/'+fixture.link)
        page.get_by_text('Try a local edit in EN',exact=True).click()
        page.locator('#edit-en').fill(fixture.quotes['en'].replace('1000','1100'))
        page.locator('form[action$="/edit"]').first.get_by_role('button',name='Save sandbox revision').click()
        notice=page.locator('.watch-notice')
        expect(notice).to_have_count(1)
        assert '1000' in notice.locator('.watch-diff del').inner_text()
        assert '1100' in notice.locator('.watch-diff ins').inner_text()
        expect(notice.locator('.source-text[lang]').first).to_be_visible()
        notice.locator('textarea[name=note]').fill('Counterpart checked; no further local update needed.')
        notice.get_by_role('button',name='No update needed',exact=True).click()
        with connect() as db,db.cursor() as c:
            c.execute('SELECT status FROM watched_notice WHERE link_id=%s',(fixture.link,))
            assert c.fetchone()['status']=='no_update'
        # Translations are also restored in the existing discrepancy review.
        page.goto('http://127.0.0.1:8010/langcompare/Q2606233?languages=en&languages=sv')
        expect(page.locator('.local-translation').first.locator('.translation-output')).not_to_contain_text('Loading',timeout=60000)
        expect(page.locator('.local-translation').first.locator('.translation-output')).not_to_contain_text('Translating',timeout=60000)
        assert 'unavailable' not in page.locator('.local-translation').first.inner_text().lower()
        assert not errors,errors
        browser.close()
    print('Watchlist UI passed: semantic discovery, confirmation, revision edit, alert, persistent review, local translations, desktop/mobile.')
finally:fixture.tearDown()
