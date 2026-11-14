"""Real WebGL navigation acceptance; software rendering is not a GPU benchmark."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ORIGIN = os.environ['LIBRARY_BROWSER_ORIGIN'].rstrip('/')
EVIDENCE = Path(os.environ.get('LIBRARY_BROWSER_EVIDENCE', '/evidence'))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        page = browser.new_page(viewport={'width':1280,'height':800}, reduced_motion='no-preference')
        page.set_default_timeout(45000)
        expect.set_options(timeout=45000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(ORIGIN+'/')
        expect(page.locator('.scene canvas')).to_be_visible()
        # Projected labels drift continuously; exercise their real keyboard action.
        page.get_by_role('button', name='Enter Round Tower (Vyborg) history', exact=True).press('Enter')
        expect(page.locator('.corridor-heading h1')).to_have_text('Round Tower (Vyborg)')
        page.get_by_role('button', name='Suomi', exact=True).click()
        expect(page.locator('.corridor-description')).to_contain_text('49 real editions')
        slider=page.get_by_role('slider', name='Walk through revision history')
        canvas=page.locator('.scene canvas')
        expect(slider).to_have_attribute('max','48')
        page.wait_for_function("() => Number(document.querySelector('.scene canvas')?.dataset.activeEditions)>0")
        start=canvas.evaluate('(node)=>({...node.dataset})')
        assert int(start['activeEditions'])<=28
        # Real wheel input moves deeper into the corridor, without selecting a book.
        page.mouse.move(640,440)
        page.mouse.wheel(0,800)
        page.wait_for_function("() => Number(document.querySelector('.scene canvas')?.dataset.camera.split(',')[2]) < -3")
        forward=canvas.get_attribute('data-camera')
        page.get_by_role('button',name='Walk to oldest edition',exact=True).click()
        page.wait_for_function("() => Math.abs(Number(document.querySelector('.scene canvas')?.dataset.camera.split(',')[2])+120)<0.01")
        expect(page.locator('.walk-current')).to_contain_text('49')
        expect(page.locator('.edition-label').filter(has_text='Edition 49')).to_be_visible()
        end=canvas.evaluate('(node)=>({...node.dataset})')
        assert int(end['activeEditions'])<=28
        assert 0<float(end['activeMs']) and 0<int(end['frames'])
        page.get_by_role('button',name='Open this edition',exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        frame=page.locator('iframe').content_frame
        expect(frame.locator('#palimpsest-blame[data-state="ready"]')).to_be_visible()
        page.wait_for_timeout(700)  # Allow the scene's 500 ms telemetry sample to settle.
        frozen=canvas.get_attribute('data-camera')
        frozen_frames=canvas.get_attribute('data-frames')
        page.wait_for_timeout(700)
        assert canvas.get_attribute('data-frames')==frozen_frames
        assert canvas.get_attribute('data-camera')==frozen
        wiki_link=page.get_by_role('link',name='Open in Palimpsest').get_attribute('href')
        source_link=page.get_by_role('link',name='Original Wikipedia edition').get_attribute('href')
        assert 'oldid=11' in wiki_link, wiki_link
        assert 'oldid=325335' in source_link, source_link
        page.get_by_role('button',name='Close book and return to corridor',exact=True).click()
        page.wait_for_timeout(700)
        restored=canvas.get_attribute('data-camera')
        assert restored==frozen,(restored,frozen)
        assert page.get_by_role('button',name='Open this edition',exact=True).evaluate('(node)=>node===document.activeElement')
        # Exercise actual WebGL context loss, rather than replacing app responses.
        canvas.evaluate("node=>node.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()")
        expect(page.locator('.scene canvas')).to_have_count(0)
        expect(page.locator('.edition-list button')).to_have_count(49)
        page.get_by_role('button',name='Palimpsest library home',exact=True).click()
        expect(page.locator('.catalog-row')).to_have_count(3)
        expect(page.locator('.list-note')).to_contain_text('3D is unavailable')
        assert not errors,errors
        result={'passed':True,'renderer':'Chromium ANGLE SwiftShader (functional only)','wheelCamera':forward,'newestWindow':start,'oldestWindow':end,'pausedCamera':frozen,'restoredCamera':restored,'localEditionLink':wiki_link,'sourceEditionLink':source_link,'contextLossFallback':True,'pageErrors':errors}
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        (EVIDENCE/'spatial-browser.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'passed':True,'checks':['guided topic entry','forward wheel','49 editions across bounded windows','reader pause','exact return/focus','local/source identities','actual context-loss fallback']}))
        browser.close()


if __name__=='__main__':
    main()
