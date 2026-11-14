"""Read-only Playwright acceptance for the seeded revision-colour article.

Run with the pinned Playwright 1.65.1 browser image. This checker never seeds
or changes application data. It requires an explicit article URL, exact quote,
and one expected last-changing revision ID per whitespace-delimited quote
token. Optional event lists independently assert focused lineage and that
Show full selection restores the selected quote's complete history.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any, TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

if TYPE_CHECKING:
    from playwright.sync_api import Page

expect = None
sync_playwright = None


def groups_from_tokens(quote: str, owners: list[str]) -> list[dict[str, Any]]:
    tokens = list(re.finditer(r"\S+", quote))
    if len(tokens) != len(owners):
        raise ValueError(f"quote has {len(tokens)} whitespace-delimited tokens; received {len(owners)} owner IDs")
    by_owner: dict[str, list[str]] = {}
    ordered: list[str] = []
    previous = None
    for match, owner in zip(tokens, owners):
        if owner not in by_owner:
            by_owner[owner] = []
            ordered.append(owner)
        if owner != previous:
            by_owner[owner].append(match.group())
        else:
            by_owner[owner][-1] += " " + match.group()
        previous = owner
    return [{"id": owner, "fragments": by_owner[owner]} for owner in ordered]


def contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(part) / 255 for part in re.findall(r"\d+", color)[:3]]
        if len(channels) != 3:
            raise AssertionError(f"not a computed RGB color: {color!r}")
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def rgb_distance(first: str, second: str) -> float:
    a = [int(part) for part in re.findall(r"\d+", first)[:3]]
    b = [int(part) for part in re.findall(r"\d+", second)[:3]]
    if len(a) != 3 or len(b) != 3:
        raise AssertionError(f"not computed RGB colors: {first!r}, {second!r}")
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def url_with_blame_action(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["action"] = ["blame"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def navigate_ready(page: Page, url: str, quote: str) -> None:
    page.goto(url_with_blame_action(url), wait_until="domcontentloaded")
    page.wait_for_function(
        """quote => {
          const article=document.querySelector('#mw-content-text .mw-parser-output');
          const panel=document.querySelector('#palimpsest-blame');
          if(!article||!panel||panel.dataset.state==='loading')return false;
          const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT);let text='';
          while(walker.nextNode())text+=walker.currentNode.nodeValue||'';
          return text.includes(quote)&&panel.dataset.state==='ready';
        }""",
        arg=quote,
        timeout=25000,
    )


def apply_skin_theme(page: Page, theme: str) -> None:
    page.emulate_media(color_scheme="dark" if theme == "night" else "light")
    page.evaluate(
        """theme => {
          const root=document.documentElement;
          root.classList.remove('skin-theme-clientpref-day','skin-theme-clientpref-night','skin-theme-clientpref-os');
          root.classList.add(theme==='night'?'skin-theme-clientpref-night':'skin-theme-clientpref-day');
          return new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        }""",
        theme,
    )


def select_exact_quote(page: Page, quote: str) -> None:
    selected = page.evaluate(
        """quote => {
          const article=document.querySelector('#mw-content-text .mw-parser-output');if(!article)return null;
          const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT);
          const nodes=[];let text='';while(walker.nextNode()){nodes.push({node:walker.currentNode,start:text.length});text+=walker.currentNode.nodeValue||'';}
          const begin=text.indexOf(quote);if(begin<0||text.indexOf(quote,begin+1)>=0)return null;
          const point=(offset,end)=>{for(const item of nodes){const length=item.node.nodeValue.length;if(offset>=item.start&&(offset<item.start+length||(end&&offset===item.start+length)))return{node:item.node,offset:offset-item.start};}return null;};
          const start=point(begin,false),finish=point(begin+quote.length,true);if(!start||!finish)return null;
          const range=document.createRange();range.setStart(start.node,start.offset);range.setEnd(finish.node,finish.offset);
          const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
          return selection.toString();
        }""",
        quote,
    )
    if selected != quote:
        raise AssertionError(f"could not select the unique exact seeded quote: {quote!r}")
    inspect = page.get_by_role("button", name=re.compile(r"Inspect selected article text|Inspect selection|Analyze selection", re.I))
    expect(inspect).to_be_visible()
    inspect.click()
    expect(page.locator(".pb-breakdown")).to_be_visible()
    if page.locator(".pb-selected-text").evaluate("el => el.textContent") != quote:
        raise AssertionError("opened history did not retain the exact selected quote")


def css_color_samples(locator, surface: str, text_backdrop: str | None = None) -> list[dict[str, Any]]:
    return locator.evaluate(
        """(root,options) => {
          const {surface,textBackdrop}=options;
          const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
          const ctx=canvas.getContext('2d',{willReadFrequently:true});
          const alphaOf=color=>{
            const slash=color.match(/\\/\\s*([\\d.]+%?)/);
            if(slash)return slash[1].endsWith('%')?parseFloat(slash[1])/100:parseFloat(slash[1]);
            const rgba=color.match(/^rgba\\((.*)\\)$/);if(rgba){const parts=rgba[1].split(',');if(parts.length===4)return parseFloat(parts[3]);}
            return 1;
          };
          const paint=(color,underlay=surface)=>{
            ctx.clearRect(0,0,1,1);ctx.fillStyle=underlay;ctx.fillRect(0,0,1,1);
            ctx.fillStyle=color;ctx.fillRect(0,0,1,1);
            const [r,g,b]=ctx.getImageData(0,0,1,1).data;
            return `rgb(${r}, ${g}, ${b})`;
          };
          const nodes=[root,...root.querySelectorAll('*')];
          const values=[];
          for(const node of nodes){
            const style=getComputedStyle(node);
            values.push({background:style.backgroundColor,painted:paint(style.backgroundColor),alpha:alphaOf(style.backgroundColor),color:style.color,foregroundPainted:paint(style.color,textBackdrop),hasText:node.textContent.trim().length>0,border:style.borderTopColor});
            for(const pseudo of ['::before','::after']){
              const p=getComputedStyle(node,pseudo);
              if(p.content&&p.content!=='none')values.push({background:p.backgroundColor,painted:paint(p.backgroundColor),alpha:alphaOf(p.backgroundColor),color:p.color,foregroundPainted:paint(p.color,textBackdrop),hasText:false,border:p.borderTopColor});
            }
          }
          return values;
        }""",
        {"surface": surface, "textBackdrop": text_backdrop or surface},
    )


def assert_meaningful_fill(samples: list[dict[str, Any]], surface: str, label: str) -> str:
    # Composite computed alpha over the actual page surface and require a
    # substantially opaque fill; RGB distance alone would misread a faint wash.
    candidates = [sample for sample in samples if sample["alpha"] >= 0.72]
    candidates = [sample for sample in candidates if rgb_distance(sample["painted"], surface) >= 40]
    if not candidates:
        raise AssertionError(f"{label} has no meaningfully filled revision color against page surface {surface}")
    return candidates[0]["painted"]


def verify_rendered_colors(page: Page, groups: list[dict[str, Any]]) -> None:
    surface = page.evaluate(
        """() => {
          const alpha=color=>{const m=color.match(/^rgba\\((.*)\\)$/);return m&&m[1].split(',').length===4?parseFloat(m[1].split(',')[3]):1;};
          for(const node of [document.body,document.documentElement]){
            const color=getComputedStyle(node).backgroundColor;
            if(alpha(color)>0)return color;
          }
          return 'rgb(255, 255, 255)';
        }"""
    )
    fills: dict[str, str] = {}
    event_ids = set(page.locator(".pb-event[data-pb-revision-id]").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)"))
    for group in groups:
        revision_id = group["id"]
        article = page.locator(f'.pb-attributed[data-pb-revision-id="{revision_id}"]').first
        phrase = page.locator(f'.pb-selection-phrase[data-pb-revision-id="{revision_id}"]').first
        revision_group = page.locator(f'.pb-revision-group[data-pb-revision-id="{revision_id}"]').first
        event = page.locator(f'.pb-event[data-pb-revision-id="{revision_id}"]').first
        for label, locator in (("article", article), ("selected quote", phrase), ("revision group", revision_group)):
            expect(locator).to_be_visible()
        if revision_id not in event_ids:
            raise AssertionError(f"no history event is labelled with selected owner revision {revision_id}")
        expect(event).to_be_visible()

        fill = assert_meaningful_fill(css_color_samples(article, surface), surface, f"article owner {revision_id}")
        for label, locator in (("selected quote", phrase), ("revision group", revision_group), ("history event", event)):
            samples = css_color_samples(locator, surface)
            matching = [sample for sample in samples if sample["painted"] == fill and sample["alpha"] >= 0.72]
            if not matching:
                raise AssertionError(f"owner {revision_id} color does not match between article and {label} (expected {fill})")
            foregrounds = {sample["foregroundPainted"] for sample in samples if sample.get("hasText", False)}
            if not foregrounds or min(contrast_ratio(foreground, fill) for foreground in foregrounds) < 4.5:
                raise AssertionError(f"owner {revision_id} text contrast is below 4.5:1 in {label} against {fill}")
        fills[revision_id] = fill

    values = list(fills.values())
    if len(set(values)) != len(values) or any(rgb_distance(a, b) < 48 for i, a in enumerate(values) for b in values[i + 1 :]):
        raise AssertionError(f"revision fills are not visibly distinct: {fills}")
    return fills


def assert_quote_ownership(page: Page, quote: str, owners: list[str], groups: list[dict[str, Any]]) -> None:
    selected = page.locator(".pb-selected-text")
    if selected.evaluate("el => el.textContent") != quote:
        raise AssertionError("the selected quote changed while rendering ownership segments")
    ownership = selected.evaluate(
        """(root,args) => {
          const {quote,owners}=args;
          const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
          const segments=[];let actual='';
          while(walker.nextNode()){
            const node=walker.currentNode,text=node.nodeValue||'';
            if(!text)continue;
            const owner=node.parentElement?.closest('.pb-selection-phrase[data-pb-revision-id]')?.dataset.pbRevisionId||null;
            segments.push({start:actual.length,end:actual.length+text.length,owner,text});
            actual+=text;
          }
          if(actual!==quote)return {actual,segments,reason:'text-mismatch'};
          const expected=Array(quote.length).fill(null);
          const tokens=[...quote.matchAll(/\\S+/gu)];
          if(tokens.length!==owners.length)return {actual,segments,reason:'token-count'};
          tokens.forEach((token,index)=>{
            for(let offset=token.index;offset<token.index+token[0].length;offset++)expected[offset]=String(owners[index]);
          });
          for(const segment of segments){
            for(let offset=segment.start;offset<segment.end;offset++){
              if(!/\\s/u.test(quote[offset])&&segment.owner!==expected[offset]){
                return {actual,segments,reason:'owner-mismatch',offset,expected:expected[offset],observed:segment.owner};
              }
            }
          }
          return {actual,segments,reason:null};
        }""",
        {"quote": quote, "owners": owners},
    )
    if ownership["reason"]:
        raise AssertionError(f"selected quote character ownership differs from expected token intervals: {ownership!r}")
    observed = [segment for segment in ownership["segments"] if segment["owner"] is not None]
    if not observed:
        raise AssertionError("selected quote has no revision-owned phrase segments")

    actual_ids = page.locator(".pb-revision-group[data-pb-revision-id]").evaluate_all("nodes => nodes.map(node => node.dataset.pbRevisionId)")
    expected_ids = [group["id"] for group in groups]
    if actual_ids != expected_ids:
        raise AssertionError(f"revision groups must appear once per owner in quote order: {actual_ids!r} != {expected_ids!r}")
    for group in groups:
        locator = page.locator(f'.pb-revision-group[data-pb-revision-id="{group["id"]}"]')
        expect(locator).to_have_count(1)
        if not re.search(rf"(?<!\d){re.escape(group['id'])}(?!\d)", locator.inner_text()):
            raise AssertionError(f"owner group {group['id']} does not visibly label its revision ID")
        for fragment in group["fragments"]:
            if locator.get_by_text(fragment, exact=True).count() < 1:
                raise AssertionError(f"owner group {group['id']} does not expose exact quote fragment {fragment!r}")


def focus_control(group_locator):
    control = group_locator.locator("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])").first
    if control.count():
        return control
    if group_locator.evaluate("el => el.matches('button,a[href],input,select,textarea,[tabindex]:not([tabindex=\"-1\"])')"):
        return group_locator
    raise AssertionError("revision group contains no keyboard-focusable activation control")


def assert_group_selected(group_locator) -> None:
    selected = group_locator.evaluate(
        """el => {
          const nodes=[el,...el.querySelectorAll('*')];
          return nodes.some(node => node.getAttribute('aria-pressed')==='true' ||
            node.getAttribute('aria-selected')==='true' || node.getAttribute('aria-current')==='true');
        }"""
    )
    if not selected:
        raise AssertionError("focused revision group has no exposed selected state")


def verify_focus_and_restore(page: Page, quote: str, groups: list[dict[str, Any]], expected_selection_events: list[str] | None, expected_focus_events: list[str] | None, excluded_events: list[str]) -> None:
    event_locator = page.locator(".pb-event[data-pb-revision-id]")
    all_visible = event_locator.evaluate_all("nodes => nodes.filter(node => !node.hidden && getComputedStyle(node).display!=='none').map(node => node.dataset.pbRevisionId)")
    if expected_selection_events is not None and all_visible != expected_selection_events:
        raise AssertionError(f"full selected-quote lineage differs: {all_visible!r} != {expected_selection_events!r}")
    if set(all_visible).intersection(excluded_events):
        raise AssertionError(f"unrelated page events appear in selected-quote history: {all_visible!r}")
    if expected_focus_events is None:
        raise AssertionError("pass --focus-event-ids to check token-lineage history after focusing a group")

    group = page.locator(f'.pb-revision-group[data-pb-revision-id="{groups[0]["id"]}"]')
    control = focus_control(group)
    if page.context.pages[0].viewport_size.get("width", 1280) > 640:
        control.focus()
        page.keyboard.press("Enter")
    else:
        control.tap()
    assert_group_selected(group)
    expect(page.get_by_role("button", name="Show full selection")).to_be_visible()
    if page.locator(".pb-selected-text").evaluate("el => el.textContent") != quote:
        raise AssertionError("focusing a revision group removed or changed the complete selected quote")
    focused = event_locator.evaluate_all("nodes => nodes.filter(node => !node.hidden && getComputedStyle(node).display!=='none').map(node => node.dataset.pbRevisionId)")
    if focused != expected_focus_events:
        raise AssertionError(f"focused history does not match expected token ancestry: {focused!r} != {expected_focus_events!r}")
    if set(focused).intersection(excluded_events):
        raise AssertionError(f"focused history includes unrelated page events: {focused!r}")

    restore = page.get_by_role("button", name="Show full selection")
    if page.context.pages[0].viewport_size.get("width", 1280) > 640:
        restore.focus()
        page.keyboard.press("Enter")
    else:
        restore.tap()
    expect(page.get_by_role("button", name="Show full selection")).not_to_be_visible()
    restored = event_locator.evaluate_all("nodes => nodes.filter(node => !node.hidden && getComputedStyle(node).display!=='none').map(node => node.dataset.pbRevisionId)")
    if restored != all_visible:
        raise AssertionError(f"Show full selection failed to restore the selected quote's full lineage: {restored!r} != {all_visible!r}")
    if page.locator(".pb-selected-text").evaluate("el => el.textContent") != quote:
        raise AssertionError("Show full selection changed the retained quote")


def verify_layout(page: Page, url: str, quote: str, owners: list[str], groups: list[dict[str, Any]], args, theme: str) -> dict[str, str]:
    navigate_ready(page, url, quote)
    apply_skin_theme(page, theme)
    select_exact_quote(page, quote)
    assert_quote_ownership(page, quote, owners, groups)
    fills = verify_rendered_colors(page, groups)
    verify_focus_and_restore(
        page,
        quote,
        groups,
        args.selection_event_ids,
        args.focus_event_ids,
        args.excluded_event_ids,
    )
    if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
        raise AssertionError("revision-colour UI overflows horizontally at this viewport")
    return fills


def main() -> int:
    global expect, sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-url", required=True, help="explicit seeded article URL; only action=blame is added")
    parser.add_argument("--quote", required=True, help="exact unique selected quote")
    parser.add_argument("--owners", required=True, help="comma-separated last-changing revision IDs, one per quote token")
    parser.add_argument("--selection-event-ids", required=True, help="comma-separated exact full selected-quote event lineage")
    parser.add_argument("--focus-event-ids", required=True, help="comma-separated exact lineage expected after focusing first owner group")
    parser.add_argument("--excluded-event-ids", default="", help="comma-separated unrelated page event IDs which must never appear")
    args = parser.parse_args()
    try:
        from playwright.sync_api import expect as playwright_expect, sync_playwright as playwright_sync
    except ImportError as error:
        parser.error(f"Playwright is required; run inside the pinned browser image ({error})")
    expect = playwright_expect
    sync_playwright = playwright_sync
    owners = [item.strip() for item in args.owners.split(",") if item.strip()]
    args.selection_event_ids = [item.strip() for item in args.selection_event_ids.split(",") if item.strip()]
    args.focus_event_ids = [item.strip() for item in args.focus_event_ids.split(",") if item.strip()]
    args.excluded_event_ids = [item.strip() for item in args.excluded_event_ids.split(",") if item.strip()]
    groups = groups_from_tokens(args.quote, owners)

    # Native probes are read-only. Explicitly select MediaWiki day/night root
    # classes and verify that the actual rendered revision fills change.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="light")
            light_fills = verify_layout(page, args.native_url, args.quote, owners, groups, args, "day")
            night_fills = verify_layout(page, args.native_url, args.quote, owners, groups, args, "night")
            if any(light_fills[revision_id] == night_fills[revision_id] for revision_id in light_fills):
                raise AssertionError(f"MediaWiki night theme did not change every revision fill: day={light_fills}, night={night_fills}")
            mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, color_scheme="light")
            verify_layout(mobile, args.native_url, args.quote, owners, groups, args, "day")
        finally:
            browser.close()
    print("PASS native revision-colour checks: exact quote/groups, distinct fills, contrast, focus lineage, restoration, desktop/mobile")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise
