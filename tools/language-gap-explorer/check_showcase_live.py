from playwright.sync_api import sync_playwright,expect
with sync_playwright() as p:
 b=p.chromium.launch(channel='msedge',headless=True);page=b.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://127.0.0.1:8010/',wait_until='networkidle')
 expect(page.get_by_role('heading',name='Tornedalians',exact=True).first).to_be_visible()
 assert page.locator('.showcase-tabs a').count()==3
 page.locator('.showcase-tabs').get_by_role('link',name='Compare languages',exact=True).click()
 assert page.locator('.language-pill').count()==3
 page.get_by_role('button',name='Remove Finnish',exact=True).click();page.get_by_role('button',name='Compare languages',exact=True).first.click()
 assert page.locator('.language-pill').count()==2
 if page.locator('.local-translation:visible').count():
  expect(page.locator('.local-translation:visible').first.locator('.translation-output')).not_to_contain_text('Translating',timeout=60000)
 page.locator('.showcase-tabs').get_by_role('link',name='Update tracker',exact=True).click()
 expect(page.get_by_role('heading',name='Update tracker',exact=True)).to_be_visible()
 assert page.locator('.issues-table').count()==1
 assert page.locator('.watch-evidence').count()==0
 page.locator('.issue-link').first.click()
 assert page.locator('.compact-diff').count()>0
 expect(page.get_by_role('link',name='Open full Wikipedia diff',exact=False)).to_be_visible()
 for width,height in ((1440,1000),(390,844)):
  page.set_viewport_size({'width':width,'height':height});assert page.locator('.showcase-tabs a:visible').count()==3;assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.locator('.showcase-tabs').get_by_role('link',name='Compare languages',exact=True).click();assert page.locator('.language-pill').count()==2
 assert not errors,errors
 b.close()
print('Live app journey passed: three tabs, language selection persistence, historical revisions, desktop/mobile and no JS errors.')
