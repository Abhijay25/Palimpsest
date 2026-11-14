from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b=p.chromium.launch(channel='msedge',headless=True)
    page=b.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8010/langcompare/Q2606233?languages=en&languages=fi')
    assert page.locator('.language-pill').count()==2
    search=page.get_by_role('combobox',name='Search languages')
    search.fill('Swe')
    page.get_by_role('option',name='Swedish · Svenska').click()
    assert page.locator('.language-pill').count()==3
    page.get_by_role('button',name='Compare languages',exact=True).first.click()
    assert page.locator('.language-pill').count()==3
    assert 'pairwise' in page.locator('.selection-caption').inner_text()
    page.get_by_role('button',name='Remove Finnish').click()
    assert page.locator('.language-pill').count()==2
    page.get_by_role('button',name='Compare languages',exact=True).first.click()
    assert page.locator('.evidence-pane .language-tag').filter(has_text='FI').count()==0
    assert page.locator('.finding:not(.finding-conflict) mark').count()==0
    page.screenshot(path='screenshots/reader-desktop.png')
    # The fixture guarantees one packet, independent of live model judgments.
    page.goto('http://127.0.0.1:8010/langcompare/Q2606233?demo=1&languages=en&languages=sv')
    first=page.locator('.finding-conflict:visible').first
    assert first.locator('blockquote').count()==2
    assert first.locator('blockquote').first.is_visible()
    assert first.locator('h3').inner_text()=='2000 vs 1999'
    assert page.locator('details.review-section,details.finding-detail').count()==0
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='screenshots/reader-mobile.png')
    assert not errors,errors
    b.close()
print('Searchable language pills, pair/triplet filtering, upfront evidence and mobile layout passed.')
