"""Opt-in MediaWiki browser acceptance for three isolated local wikis.

Run only against a disposable worker-C runtime. The tests create local accounts,
pages and one upload; they use no external credentials or production endpoints.
"""

from __future__ import annotations

import json
import os
import argparse
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright
from png_fixture import png_bytes


LANGUAGES = ("fi", "sv", "en")
API_MANIFEST = Path(os.environ.get("PALIMPSEST_C1_MANIFEST", "/test-data/runtime.json"))
TEST_HOST = os.environ.get("PALIMPSEST_TEST_HOST", "host.docker.internal")
RUN_ID = uuid.uuid4().hex[:10]


def site_root(api_url: str) -> str:
    parsed = urlsplit(api_url)
    return urlunsplit((parsed.scheme, f"{TEST_HOST}:{parsed.port}", parsed.path.rsplit("/", 1)[0], "", ""))


def english_ui(url: str) -> str:
    return url + ("&" if "?" in url else "?") + "uselang=en"


def assert_image_loaded(page: Page, image_selector: str) -> None:
    image = page.locator(image_selector)
    expect(image).to_be_visible(timeout=30_000)
    page.wait_for_function(
        "selector => { const image = document.querySelector(selector); return !!image && image.complete && image.naturalWidth > 0; }",
        arg=image_selector,
        timeout=30_000,
    )


def create_account(page: Page, root: str, username: str, password: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title=Special:CreateAccount"), wait_until="domcontentloaded")
    page.locator("#wpName2").fill(username)
    page.locator("#wpPassword2").fill(password)
    if page.locator("#wpRetype").count():
        page.locator("#wpRetype").fill(password)
    submit = page.locator("#wpCreateaccount")
    if submit.count() == 0:
        submit = page.get_by_role("button", name=re.compile("create account", re.I))
    submit.first.click()
    expect(page.locator("body")).not_to_contain_text(re.compile("already exists|captcha|error", re.I))


def login(page: Page, root: str, username: str, password: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title=Special:UserLogin"), wait_until="domcontentloaded")
    page.locator("#wpName1").fill(username)
    page.locator("#wpPassword1").fill(password)
    submit = page.locator("#wpLoginAttempt")
    if submit.count() == 0:
        submit = page.get_by_role("button", name=re.compile("log in|login", re.I))
    submit.first.click()
    expect(page.locator("#wpName1")).to_have_count(0)


def logout(page: Page, root: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title=Special:UserLogout"), wait_until="domcontentloaded")
    confirm = page.locator("#mw-content-text button[type=submit], #mw-content-text input[type=submit]")
    if confirm.count():
        confirm.first.click()
    page.goto(english_ui(f"{root}/index.php?title=Special:UserLogin"), wait_until="domcontentloaded")
    expect(page.locator("#wpName1")).to_be_visible()


def save_source(page: Page, root: str, title: str, content: str, summary: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=edit"), wait_until="domcontentloaded")
    textarea = page.locator("#wpTextbox1")
    expect(textarea).to_be_visible()
    textarea.fill(content)
    page.locator("#wpSummary").fill(summary)
    page.locator("#wpSave").click()
    expect(page.locator("#mw-content-text")).to_contain_text(content.splitlines()[0])
    expect(page.locator("body")).to_have_class(re.compile(r"(?:^|\s)skin-vector-2022(?:\s|$)"))


def save_visual(page: Page, root: str, title: str, base_content: str, marker: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&veaction=edit"), wait_until="domcontentloaded")
    welcome = page.get_by_role("dialog", name=re.compile("^Welcome to", re.I))
    expect(welcome).to_be_visible(timeout=30_000)
    start_editing = welcome.get_by_role("button", name="Start editing", exact=True)
    expect(start_editing).to_be_visible()
    start_editing.click()
    expect(welcome).not_to_be_visible(timeout=30_000)
    page.wait_for_function(
        "() => { const container = document.querySelector('.mw-page-container'); return !!container && !container.inert; }",
        timeout=30_000,
    )
    surface = page.locator('.ve-ce-rootNode[role="textbox"][contenteditable="true"]')
    expect(surface).to_be_visible(timeout=60_000)
    expect(page.locator(".ve-ui-toolbar")).to_be_visible()
    # Put the caret in the document, then type at a human-like pace. VisualEditor
    # can update the editable DOM ahead of its document model during rapid input.
    surface.locator("p").first.click(position={"x": 8, "y": 8})
    page.keyboard.press("Control+End")
    page.keyboard.type(f" {marker}", delay=50)
    expect(surface).to_contain_text(marker, timeout=30_000)
    page.wait_for_function("""marker => {
        const model = window.ve?.init?.target?.getSurface?.()?.getModel?.();
        const data = model?.getDocument?.().getData?.();
        const text = Array.isArray(data) ? data.map(item =>
            typeof item === 'string' ? item : Array.isArray(item) ? item[0] : ''
        ).join('') : '';
        return !!model && text.includes(marker);
    }""", arg=marker, timeout=30_000)
    save_button = page.locator(".ve-ui-toolbar").get_by_role(
        "button", name=re.compile(r"^Save(?: changes)?(?:…|\.\.\.)?$", re.I)
    )
    expect(save_button.last).to_be_visible()
    try:
        expect(save_button.last).to_be_enabled(timeout=30_000)
    except AssertionError as error:
        state = page.evaluate("""() => {
            const root = document.querySelector('.ve-ce-rootNode[role="textbox"][contenteditable="true"]');
            const roots = document.querySelectorAll('.ve-ce-rootNode[role="textbox"][contenteditable="true"]');
            const save = document.querySelector('.ve-ui-toolbar-saveButton');
            const surface = window.ve?.init?.target?.getSurface?.();
            const view = surface?.getView?.();
            const docView = view?.getDocument?.();
            const model = surface?.getModel?.();
            const modelSelection = model?.getSelection?.();
            let modelText = null;
            let modified = null;
            let modelData = null;
            try { modified = model.hasBeenModified(); } catch (_) {}
            try { modelText = model.getDocument().getData().map(item => typeof item === 'string' ? item : Array.isArray(item) ? item[0] : '').join(''); } catch (_) {}
            try { modelData = JSON.stringify(model.getDocument().getData()).slice(0, 500); } catch (_) {}
            return {
                rootCount: roots.length,
                rootMatchesDocumentView: !!root && docView?.$element?.[0] === root,
                rootInsideSurfaceView: !!root && !!view?.$element?.[0]?.contains(root),
                documentViewClass: docView?.$element?.[0]?.className,
                rootAncestors: root ? [root, root.parentElement, root.parentElement?.parentElement].map(node => ({ className: node?.className, inert: node?.inert })) : [],
                focusedEditor: !!root && document.activeElement === root,
                editorText: root?.innerText,
                modelText,
                modelData,
                modelReadOnly: model?.isReadOnly?.(),
                modelSelection: modelSelection ? { type: modelSelection.constructor?.name, range: modelSelection.getRange?.() } : null,
                selection: window.getSelection()?.toString(),
                saveDisabled: save?.getAttribute('aria-disabled'),
                modelModified: modified,
            };
        }""")
        raise AssertionError(f"VisualEditor Save stayed disabled after inserting marker; state={json.dumps(state)}") from error
    save_button.last.click()
    save_dialog = page.locator(".ve-ui-mwSaveDialog")
    expect(save_dialog).to_be_visible(timeout=30_000)
    dialog_save = save_dialog.get_by_role("button", name=re.compile("publish changes|save changes|save page|^save$", re.I))
    expect(dialog_save.last).to_be_visible()
    dialog_save.last.click()
    expect(page.locator(".ve-ui-toolbar")).to_have_count(0, timeout=60_000)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#mw-content-text")).to_contain_text(marker, timeout=30_000)
    expect(page.locator("#mw-content-text")).to_contain_text(base_content, timeout=30_000)


def history_and_diff(page: Page, root: str, title: str) -> None:
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=history"), wait_until="domcontentloaded")
    rows = page.locator("#pagehistory li, .mw-history-compare li")
    expect(rows.first).to_be_visible(timeout=30_000)
    assert rows.count() >= 2, "history must expose at least two revisions"
    diff = page.locator("a[href*='diff=']").first
    expect(diff).to_be_visible()
    diff.click()
    expect(page.locator("table.diff")).to_be_visible()


def search_page(page: Page, root: str, title: str, phrase: str) -> None:
    page.goto(
        english_ui(f"{root}/index.php?title=Special:Search&search={quote(phrase)}"),
        wait_until="domcontentloaded",
    )
    expect(page.locator("#mw-content-text")).to_contain_text(title, timeout=45_000)


def create_talk_post_and_reply(page: Page, root: str, title: str, token: str) -> None:
    talk = f"Talk:{title}"
    first = f"== Acceptance topic {token} ==\nInitial local discussion post {token}. ~~~~"
    edit_url = english_ui(f"{root}/index.php?title={quote(talk, safe=':')}&action=edit")
    page.goto(edit_url, wait_until="domcontentloaded")
    textarea = page.locator("#wpTextbox1")
    expect(textarea).to_be_visible()
    textarea.fill(first)
    page.locator("#wpSummary").fill("Create acceptance discussion topic")
    page.locator("#wpSave").click()
    expect(page.locator("#mw-content-text h2")).to_contain_text(f"Acceptance topic {token}")

    reply_link = page.get_by_role("button", name="Reply", exact=True)
    expect(reply_link.first).to_be_visible(timeout=30_000)
    # DiscussionTools binds reply-click handlers after its content hook runs.
    # The pinned extension sets this class only after controller initialization.
    expect(page.locator("html")).to_have_class(
        re.compile(r"(?:^|\s)ext-discussiontools-init-ready(?:\s|$)"), timeout=30_000
    )
    reply_link.first.click()
    reply_input = page.get_by_role("textbox", name=re.compile("^Reply to", re.I)).last
    expect(reply_input).to_be_visible(timeout=30_000)
    marker = f"DiscussionTools reply acceptance {token}"
    reply_input.click()
    page.keyboard.type(marker, delay=50)
    typed_reply = reply_input.evaluate("element => element.value ?? element.innerText ?? element.textContent ?? ''")
    assert marker in typed_reply, f"DiscussionTools composer did not retain the full reply text: {typed_reply!r}"
    page.wait_for_function("""marker => {
        const input = document.querySelector('.ext-discussiontools-ui-replyWidget [role="textbox"][contenteditable="true"]');
        const view = input && window.jQuery ? window.jQuery(input).data('view') : null;
        const model = view?.getModel?.();
        const data = model?.getDocument?.().getData?.();
        const text = Array.isArray(data) ? data.map(item =>
            typeof item === 'string' ? item : Array.isArray(item) ? item[0] : ''
        ).join('') : '';
        return !!model && model.hasBeenModified() && text.includes(marker);
    }""", arg=marker, timeout=30_000)
    submit_reply = page.get_by_role("button", name="Reply", exact=True)
    try:
        expect(submit_reply.last).to_be_enabled(timeout=30_000)
    except AssertionError as error:
        state = page.evaluate("""() => ({
            modelData: (() => {
                const input=document.querySelector('.ext-discussiontools-ui-replyWidget [role="textbox"][contenteditable="true"]');
                const model=input && window.jQuery ? window.jQuery(input).data('view')?.getModel?.() : null;
                return model?.getDocument?.().getData?.();
            })(),
            widgets: [...document.querySelectorAll('.ext-discussiontools-ui-replyWidget')].map(node => ({className: node.className, text: node.innerText})),
            textboxes: [...document.querySelectorAll('[role="textbox"]')].map(node => ({tag: node.tagName, className: node.className, value: node.value, text: node.innerText, label: node.getAttribute('aria-label')})),
            replyButtons: [...document.querySelectorAll('[role="button"]')].filter(node => node.innerText.trim() === 'Reply').map(node => ({disabled: node.getAttribute('aria-disabled'), className: node.className, title: node.title})),
        })""")
        raise AssertionError(f"DiscussionTools Reply stayed disabled after full text input: {json.dumps(state)}") from error
    submit_reply.last.click()
    reply_widget = page.locator(".ext-discussiontools-ui-replyWidget")
    expect(reply_widget).to_have_count(0, timeout=60_000)
    expect(page.locator("#mw-content-text")).to_contain_text(marker, timeout=60_000)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#mw-content-text")).to_contain_text(marker, timeout=30_000)


def watch_and_check_second_user_edit(
    browser: Browser, watcher_context: BrowserContext, root: str, title: str,
    user_one: tuple[str, str], user_two: tuple[str, str], token: str
) -> None:
    watcher = watcher_context.new_page()
    login(watcher, root, *user_one)
    watcher.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=watch"), wait_until="domcontentloaded")
    watcher.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}"), wait_until="domcontentloaded")
    expect(watcher.locator("a[href*='action=unwatch'], a[title*='Unwatch']")).to_be_visible()

    second_context = browser.new_context()
    editor = second_context.new_page()
    login(editor, root, *user_two)
    editor.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=edit"), wait_until="domcontentloaded")
    textarea = editor.locator("#wpTextbox1")
    textarea.fill(textarea.input_value() + f"\nSecond user watchlist marker {token}")
    editor.locator("#wpSummary").fill("Second user watchlist acceptance edit")
    editor.locator("#wpSave").click()
    expect(editor.locator("#mw-content-text")).to_contain_text(f"Second user watchlist marker {token}")
    logout(editor, root)
    editor.close()
    second_context.close()

    watcher.goto(english_ui(f"{root}/index.php?title=Special:Watchlist"), wait_until="domcontentloaded")
    expect(watcher.locator("#mw-content-text")).to_contain_text(title)
    expect(watcher.locator("#mw-content-text")).to_contain_text(user_two[0])
    expect(watcher.locator("#mw-content-text")).to_contain_text("Second user watchlist acceptance edit")
    watcher.close()


def upload_and_render_image(page: Page, root: str, title: str, token: str) -> None:
    png = png_bytes()
    filename = f"InfraAcceptance{token}.png"
    with tempfile.TemporaryDirectory(prefix="palimpsest-c-upload-") as temp_dir:
        local_file = Path(temp_dir) / filename
        local_file.write_bytes(png)
        page.goto(english_ui(f"{root}/index.php?title=Special:Upload"), wait_until="domcontentloaded")
        page.locator("#wpUploadFile").set_input_files(str(local_file))
        page.locator("#wpDestFile").fill(filename)
        submit = page.locator("#wpUpload")
        if submit.count() == 0:
            submit = page.get_by_role("button", name=re.compile("upload", re.I))
        submit.first.click()
        expect(page.locator("#mw-content-text")).to_contain_text(filename, timeout=60_000)
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=edit"), wait_until="domcontentloaded")
    current = page.locator("#wpTextbox1")
    current.fill(current.input_value() + f"\n[[File:{filename}|thumb|local upload {token}]]")
    page.locator("#wpSummary").fill("Render uploaded acceptance image")
    page.locator("#wpSave").click()
    assert_image_loaded(page, f"img[src*='{quote(filename)}']")


def assert_anonymous_read_and_edit_boundary(context: BrowserContext, root: str, title: str) -> None:
    page = context.new_page()
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}"), wait_until="domcontentloaded")
    expect(page.locator("#mw-content-text")).to_be_visible()
    page.goto(english_ui(f"{root}/index.php?title={quote(title, safe=':')}&action=protect"), wait_until="domcontentloaded")
    # Protect is core administrator-only; do not assume anonymous edit policy.
    expect(page.locator("#wpProtectSettings")).to_have_count(0)
    expect(page.locator("#mw-content-text")).to_contain_text(re.compile("permission|not allowed|log in|cannot", re.I))
    page.close()


def run_language(browser: Browser, language: str, runtime: dict) -> dict:
    token = f"{language}-{RUN_ID}"
    root = site_root(runtime["languages"][language]["api_url"])
    password = f"T08-{uuid.uuid4().hex}-A9!"
    # Reusing account and page names across wikis proves identity/data isolation:
    # a shared user table or shared page store would collide or overwrite content.
    users = (f"InfraA{RUN_ID}", f"InfraB{RUN_ID}")
    title = f"Infra acceptance {RUN_ID}"

    context = browser.new_context()
    page = context.new_page()
    api_response = page.goto(english_ui(f"{root}/api.php?action=query&meta=siteinfo&siprop=general&format=json"), wait_until="domcontentloaded")
    assert api_response is not None and api_response.status == 200, f"{language} API is not reachable through host gateway"
    general = json.loads(page.locator("body").inner_text())["query"]["general"]
    assert general.get("lang") == language, f"expected site language {language}, got {general.get('lang')!r}"
    expected_db = runtime["languages"][language]["database"]
    # MediaWiki Siteinfo has no dbname property. If a deployment adds one, verify
    # it; cross-wiki same-name account/page tests below prove isolation behavior.
    if general.get("dbname") is not None:
        assert general["dbname"] == expected_db, f"C1/API database mismatch for {language}"
    create_account(page, root, users[0], password)
    logout(page, root)
    create_account(page, root, users[1], password)
    logout(page, root)
    login(page, root, users[0], password)
    first_body = f"Source editor acceptance {token}.\nInitial durable text."
    save_source(page, root, title, first_body, "Create source edit acceptance page")
    save_visual(page, root, title, first_body, f"Visual editor acceptance marker {token}")
    search_page(page, root, title, "Initial durable text")
    history_and_diff(page, root, title)
    create_talk_post_and_reply(page, root, title, token)
    upload_and_render_image(page, root, title, token)
    logout(page, root)

    watch_and_check_second_user_edit(browser, context, root, title, (users[0], password), (users[1], password), token)
    logout(page, root)
    assert_anonymous_read_and_edit_boundary(context, root, title)
    context.close()
    print(f"PASS {language}: account/login/logout, source+visual saves, history/diff, talk, watchlist, upload and permissions")
    return {
        "language": language,
        "root": root,
        "users": users,
        "password": password,
        "title": title,
        "source_marker": f"Source editor acceptance {token}.",
        "visual_marker": f"Visual editor acceptance marker {token}",
        "talk": f"Talk:{title}",
        "talk_marker": f"DiscussionTools reply acceptance {token}",
        "watch_summary": "Second user watchlist acceptance edit",
        "second_user_marker": f"Second user watchlist marker {token}",
        "filename": f"InfraAcceptance{token}.png",
    }


def verify_persistence(browser: Browser, records: list[dict]) -> None:
    for record in records:
        language = record["language"]
        context = browser.new_context()
        page = context.new_page()
        login(page, record["root"], record["users"][0], record["password"])
        page.goto(english_ui(f"{record['root']}/index.php?title={quote(record['title'], safe=':')}"), wait_until="domcontentloaded")
        for marker in (record["source_marker"], record["visual_marker"], record["second_user_marker"]):
            expect(page.locator("#mw-content-text")).to_contain_text(marker)
        assert_image_loaded(page, f"img[src*='{quote(record['filename'])}']")
        page.goto(english_ui(f"{record['root']}/index.php?title={quote(record['talk'], safe=':')}"), wait_until="domcontentloaded")
        expect(page.locator("#mw-content-text")).to_contain_text(record["talk_marker"])
        page.goto(english_ui(f"{record['root']}/index.php?title=Special:Watchlist"), wait_until="domcontentloaded")
        expect(page.locator("#mw-content-text")).to_contain_text(record["users"][1])
        expect(page.locator("#mw-content-text")).to_contain_text(record["watch_summary"])
        page.goto(english_ui(f"{record['root']}/index.php?title={quote(record['title'], safe=':')}&action=history"), wait_until="domcontentloaded")
        history_rows = page.locator("#pagehistory li, .mw-history-compare li")
        expect(history_rows.first).to_be_visible()
        assert history_rows.count() >= 3, f"{language} history did not survive restart"
        logout(page, record["root"])
        assert_anonymous_read_and_edit_boundary(context, record["root"], record["title"])
        context.close()

        second_context = browser.new_context()
        second_user = second_context.new_page()
        login(second_user, record["root"], record["users"][1], record["password"])
        logout(second_user, record["root"])
        second_context.close()
        print(f"PASS {language}: account, edits, history, discussion, watchlist and upload survived down/setup")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-state", help="verify previously created browser state after runtime restart")
    args = parser.parse_args()
    if not API_MANIFEST.is_file():
        raise SystemExit(f"C1 runtime manifest not found: {API_MANIFEST}")
    runtime = json.loads(API_MANIFEST.read_text(encoding="utf-8"))
    if runtime.get("schema_version") != 1 or set(runtime.get("languages", {})) != set(LANGUAGES):
        raise SystemExit("C1 manifest must be schema v1 and contain fi, sv, en")
    databases = [runtime["languages"][language].get("database") for language in LANGUAGES]
    if not all(databases) or len(set(databases)) != len(LANGUAGES):
        raise SystemExit("C1 must declare a distinct database identity for each language")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            if args.verify_state:
                records = json.loads(Path(args.verify_state).read_text(encoding="utf-8"))
                if {row.get("language") for row in records} != set(LANGUAGES):
                    raise SystemExit("persistence state must contain fi, sv and en")
                verify_persistence(browser, records)
            else:
                records = [run_language(browser, language, runtime) for language in LANGUAGES]
                state_path = Path(os.environ.get("PALIMPSEST_BROWSER_STATE", "/test-data/browser-state.json"))
                state_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
