"""Read-only native acceptance against an explicitly supplied real Library origin.

Run in the existing pinned palimpsest-blame-browser:1.65.1 image. No response
fixtures, page seeding, or programmatic Selection.addRange are used.
"""
import json
import os
from pathlib import Path
import re
from playwright.sync_api import sync_playwright, expect

ORIGIN = os.environ['LIBRARY_BROWSER_ORIGIN'].rstrip('/')
EVIDENCE = Path(os.environ.get('LIBRARY_BROWSER_EVIDENCE', '/evidence'))
PHRASE = 'Torni rakennettiin vuosina 1547–1550'
# Frozen original-source identities audited in the retained public C3 revisions:
# 325335 first wording; 330197 year/link target; 331279 verb;
# 17859948 en dash; 22513700 restores the sentence's opening noun.
OWNER_SOURCE_IDS = {325335, 330197, 331279, 17859948, 22513700}

def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':1280,'height':800}, reduced_motion='reduce')
        page = context.new_page()
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        catalog=context.request.get(ORIGIN+'/api/catalog').json()
        topic=next(row for row in catalog['topics'] if row['id']=='Q4241896')
        fi=topic['articles']['fi']
        history=context.request.get(ORIGIN+'/api/topics/Q4241896/revisions?lang=fi').json()['versions']
        source_to_local={row['source']['revision_id']:row['revision_id'] for row in history}
        expected_owners={source_to_local[source_id] for source_id in OWNER_SOURCE_IDS}
        analysis=context.request.get(ORIGIN+'/api/wiki/fi',params={'action':'palimpsestblame','op':'analyze','title':fi['title'],'revision':fi['anchorRevision'],'ranges':json.dumps([{'start':311,'end':347}])}).json()['palimpsestblame']
        assert analysis['status']=='ready'
        encoded_source=analysis['source_text'].encode('utf-16-le')
        word_owners={span['revision_id'] for span in analysis['spans'] if span['start']<347 and span['end']>311 and encoded_source[max(311,span['start'])*2:min(347,span['end'])*2].decode('utf-16-le').strip()}
        # The API's revision_ids also includes selected whitespace ownership;
        # the reader's word groups must not manufacture a whitespace-only group.
        assert word_owners == expected_owners, (word_owners,expected_owners)
        expected_events={row['revision_id'] for row in analysis['selection']['events']}
        page.goto(ORIGIN+f'/#topic=Q4241896&lang=fi&view=reader&revision={fi["anchorRevision"]}')
        expect(page.get_by_role('dialog')).to_be_visible()
        frame=page.locator('iframe').content_frame
        expect(frame.locator('#palimpsest-blame[data-state="ready"]')).to_be_visible()
        frame.locator('body').evaluate('() => document.fonts.ready')
        first=frame.locator('.mw-parser-output [data-pb-start="311"]')
        last=frame.locator('.mw-parser-output [data-pb-start="343"]')
        assert first.inner_text()=='Torni'
        assert last.inner_text()=='1550'
        first.scroll_into_view_if_needed()
        a,b=first.bounding_box(),last.bounding_box()
        frame.locator('body').evaluate('''() => { window.__selectionTrace=[]; for(const type of ['mousedown','mousemove','mouseup','pointerdown','pointerup','selectstart','selectionchange','dragstart']) document.addEventListener(type,event=>{setTimeout(()=>{const s=window.getSelection();window.__selectionTrace.push({type,selection:s.toString(),anchor:s.anchorNode?.parentElement?.getAttribute('data-pb-start'),focus:s.focusNode?.parentElement?.getAttribute('data-pb-start'),buttons:event.buttons,trusted:event.isTrusted,prevented:event.defaultPrevented,target:event.target.tagName});},0);}); }''')
        page.mouse.move(a['x']+.4,a['y']+a['height']/2)
        page.mouse.down()
        page.mouse.move(b['x']+b['width']-.4,b['y']+b['height']/2,steps=18)
        page.mouse.up()
        native_selection=frame.locator('body').evaluate('() => window.getSelection().toString()')
        if native_selection!=PHRASE:
            diagnostic=frame.locator('body').evaluate('''() => ({trace:window.__selectionTrace,selection:window.getSelection().toString(),parents:Array.from(document.querySelectorAll('[data-pb-start="311"],.mw-parser-output,body,html')).map(n=>({tag:n.tagName,role:n.getAttribute('role'),userSelect:getComputedStyle(n).userSelect,draggable:n.draggable,inert:n.inert,rect:n.getBoundingClientRect().toJSON()}))})''')
            diagnostic['boxes']={'first':a,'last':b}
            (EVIDENCE/'selection-diagnostics.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
            page.screenshot(path=str(EVIDENCE/'selection-failure.png'))
        assert native_selection==PHRASE, repr(native_selection)
        expect(first).to_have_attribute('role','button')
        expect(first).to_have_attribute('tabindex','0')
        frame.locator('.reader-inspect').click()
        expect(frame.locator('.pb-selected-text')).to_have_text(PHRASE)
        owners=set(map(int,frame.locator('.pb-revision-group').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.pbRevisionId)')))
        assert owners==expected_owners, (owners,expected_owners)
        events=set(map(int,frame.locator('.pb-event').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.pbRevisionId)')))
        assert events==expected_events, (events,expected_events)
        colors=frame.locator('.pb-selection-phrase').evaluate_all('''nodes=>nodes.filter(n=>n.textContent.trim()).map(n=>({owner:n.dataset.pbRevisionId,color:getComputedStyle(n).backgroundColor}))''')
        assert len({row['color'] for row in colors})>=3
        for row in colors:
            article_color=frame.locator('.mw-parser-output .pb-attributed[data-pb-revision-id="'+row['owner']+'"]').first.evaluate('(node)=>getComputedStyle(node).backgroundColor')
            assert article_color==row['color']
        placement=frame.locator('#palimpsest-blame').evaluate('(node)=>({after:node.previousElementSibling?.tagName,first:node.firstElementChild?.className})')
        assert placement['after']=='P' and 'pb-breakdown' in placement['first'], placement
        page.screenshot(path=str(EVIDENCE/'reader-inline-chromium.png'))
        results.append({'case':'native mixed-word mouse selection','quote':PHRASE,'ownerSourceIds':sorted(OWNER_SOURCE_IDS),'localOwners':sorted(owners),'events':sorted(events),'colors':colors,'placement':placement})

        dialog=page.get_by_role('dialog')
        dialog.get_by_role('button',name='Svenska',exact=True).click()
        sv=topic['articles']['sv']
        expect(page.locator('iframe')).to_have_attribute('src',f'/reader/Q4241896/sv/{sv["anchorRevision"]}')
        frame=page.locator('iframe').content_frame
        expect(frame.locator('#palimpsest-blame[data-state="ready"]')).to_be_visible()
        assert frame.locator('.pb-breakdown').count()==0
        expect(page.locator('.sr-only')).to_contain_text('Language changed to Svenska')
        assert page.locator('.book-heading p').inner_text().endswith('revision '+str(sv['anchorRevision']))
        results.append({'case':'language changes to latest imported edition','language':'sv','revision':sv['anchorRevision'],'announcement':page.locator('.sr-only').inner_text()})

        word=frame.locator('.pb-attributed[role="button"]').filter(has_text=re.compile(r'\w')).first
        word.focus()
        word.press('Enter')
        expect(frame.locator('.pb-breakdown')).to_be_visible()
        page.keyboard.press('Escape')
        expect(frame.locator('.pb-breakdown')).to_have_count(0)
        expect(page.get_by_role('dialog')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        results.append({'case':'Escape closes inline inspection before the reader','passed':True})

        for fragment,message in [
            ('#view=reader','edition address is invalid'),
            ('#topic=Q0&lang=fi&view=reader&revision=1','outside the curated collection'),
            ('#topic=Q4241896&lang=de&view=reader&revision=1','language is unavailable')
        ]:
            page.goto(ORIGIN+'/'+fragment)
            expect(page.get_by_role('alert')).to_contain_text(message)
            assert page.locator('iframe').count()==0
            assert page.locator('.application').get_attribute('inert') is None
            page.get_by_role('button',name='Return to the library',exact=True).click()
            expect(page.get_by_role('alert')).to_have_count(0)
            results.append({'case':'invalid deep link','fragment':fragment,'noSubstitution':True,'recovery':True})

        narrow=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
        mobile=narrow.new_page()
        mobile.goto(ORIGIN+'/')
        expect(mobile.locator('.catalog-row')).to_have_count(3)
        mobile.locator('.catalog-row').first.click()
        expect(mobile.locator('.edition-list button').first).to_be_visible()
        mobile.locator('.edition-list button').first.click()
        mobile_frame=mobile.locator('iframe').content_frame
        expect(mobile_frame.locator('#palimpsest-blame[data-state="ready"]')).to_be_visible()
        size=mobile.evaluate('({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,height:document.documentElement.clientHeight,scrollHeight:document.documentElement.scrollHeight})')
        assert size['width']==size['scrollWidth'] and size['height']==size['scrollHeight'],size
        mobile.screenshot(path=str(EVIDENCE/'reader-mobile-chromium.png'))
        results.append({'case':'narrow reduced-motion fallback and full reader','layout':size})
        assert not errors, errors
        (EVIDENCE/'browser.json').write_text(json.dumps({'passed':True,'origin':ORIGIN,'cases':results,'pageErrors':errors},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'passed':True,'cases':len(results),'pageErrors':errors},ensure_ascii=False))
        browser.close()

if __name__=='__main__':
    main()
