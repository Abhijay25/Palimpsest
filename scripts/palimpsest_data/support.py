from __future__ import annotations

import re
import urllib.parse
import time
import hashlib
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .io import DataError, atomic_json, read_json
from .history import API, fetch_json, normalize_timestamp, revision_record, iter_page_records
from .manifests import validate_corpus

TEMPLATE_RE = re.compile(r"\{\{\s*([^{}|#]+)")
MODULE_RE = re.compile(r"\{\{\s*#invoke\s*:\s*([^|}]+)", re.IGNORECASE)
STYLE_RE = re.compile(r"<templatestyles\b[^>]*\bsrc\s*=\s*['\"]?([^\s'\">]+)", re.IGNORECASE)
LUA_RE = re.compile(r"(?:require|mw\.loadData|mw\.loadJsonData)\s*\(?\s*['\"]((?:Module|Moduuli|Modul):[^'\"]+)['\"]", re.IGNORECASE)
REDIRECT_RE = re.compile(r"^\s*#(?:redirect|ohjaus|omdirigering)\s*:?\s*\[\[([^\]|]+)", re.IGNORECASE)
ALLOWED_NAMESPACES = {"template": 10, "mall": 10, "malli": 10, "malline": 10, "module": 828, "moduuli": 828, "modul": 828}
EXPLICIT_NAMESPACES = {"category": 14, "luokka": 14, "kategori": 14}
TITLE_NAMESPACES = {**ALLOWED_NAMESPACES, **EXPLICIT_NAMESPACES, "mediawiki": 8, "järjestelmäviesti": 8}
CITE_LABEL_KEYS = {"8:Cite link label group-" + group for group in ("lower-alpha", "upper-alpha", "lower-roman", "upper-roman")}
MAGIC_WORDS = {"aakkostus", "defaultsort", "displaytitle", "forcetoc", "notoc", "toc", "newsectionlink", "nonewsectionlink"}


def title_key(title: str) -> str:
    """EN/FI/SV source namespaces use first-letter case, not case folding."""
    title=title.replace('_',' ').strip()
    if ':' not in title:return title[:1].upper()+title[1:]
    prefix,name=title.split(':',1);namespace=TITLE_NAMESPACES.get(prefix.casefold(),prefix.casefold())
    name=name.strip()
    return str(namespace)+':'+name[:1].upper()+name[1:]


def dependency_names(wikitext: str) -> list[str]:
    wikitext = re.sub(r"<!--.*?-->", "", wikitext, flags=re.DOTALL)
    wikitext = re.sub(r"\{\{\{.*?\}\}\}", "", wikitext, flags=re.DOTALL)
    names: set[str] = set()
    for m in TEMPLATE_RE.finditer(wikitext):
        name = m.group(1).strip().replace("_", " ")
        if not name or name.startswith("#") or name == "!":
            continue
        if ":" in name:
            prefix = name.split(":", 1)[0].casefold()
            if prefix in MAGIC_WORDS:
                continue
            if prefix in ALLOWED_NAMESPACES:
                names.add(name)
        else:
            names.add(f"Template:{name}")
    for m in MODULE_RE.finditer(wikitext):
        names.add(f"Module:{m.group(1).strip()}")
    for m in STYLE_RE.finditer(wikitext):
        name = m.group(1).strip()
        names.add(name if ":" in name else f"Template:{name}")
    for m in LUA_RE.finditer(wikitext):names.add(m.group(1).strip())
    for m in REDIRECT_RE.finditer(wikitext):
        target=m.group(1).strip()
        if ':' in target and target.split(':',1)[0].casefold() in ALLOWED_NAMESPACES:names.add(target)
    return sorted(names, key=str.casefold)


def _namespace_ok(title: str, allow_extra: set[int] | None = None) -> bool:
    if ":" not in title:
        return False
    prefix = title.split(":", 1)[0].casefold()
    return prefix in ALLOWED_NAMESPACES


def discover_support(root_title: str, root_text: str, cutoff: str,
                     resolver: Callable[[str, str], dict[str, Any] | None],
                     *, max_pages: int = 5000, progress_path: Path | None = None,
                     request_budget: list[int] | None = None,
                     extra_titles: tuple[str, ...] = (),
                     extra_namespaces: dict[str, int] | None = None) -> dict[str, Any]:
    """Resolve a cutoff closure and checkpoint each page before moving to the next."""
    initial = dependency_names(root_text)
    if progress_path and progress_path.exists():
        state = read_json(progress_path)
        if state.get("root_title") != root_title or state.get("cutoff") != cutoff:
            raise DataError(f"support checkpoint identity mismatch for {root_title}")
    else:
        state = {"schema_version": 1, "root_title": root_title, "cutoff": cutoff,
                 "pending": initial, "visited": [], "supporting": [], "unresolved": [], "edges": {root_title: initial},
                 "requests_made": 0}
    # Extra pages require explicit identities; additional namespaces also require
    # source-verified configuration. The four native Cite label messages are a
    # bounded core-namespace exception, still requiring an explicit page identity.
    # Category pages likewise require explicit names, never category traversal.
    # Never expand traversal to every linked page or arbitrary system messages.
    namespace_ids = {name.casefold(): nsid for name, nsid in (extra_namespaces or {}).items()
                     if isinstance(nsid, int) and 100 <= nsid < 10000 and nsid not in (828, 829)}
    allowed_titles={key for key in state.get("allowed_titles", [])
                    if ":" not in key or key.split(":", 1)[0] in namespace_ids or key.startswith('14:') or key in CITE_LABEL_KEYS} | {
        title_key(t) for t in extra_titles
        if ":" not in t or t.split(":", 1)[0].casefold() in namespace_ids or t.split(":", 1)[0].casefold() in EXPLICIT_NAMESPACES or title_key(t) in CITE_LABEL_KEYS}
    queue = deque(state.get("pending", []))
    visited = set(state.get("visited", [])) if state.get('title_key_version')==3 else {title_key(x['title']) for x in [*state.get('supporting',[]),*state.get('unresolved',[])]}
    inventory_by_title = {title_key(x["title"]): x for x in state.get("supporting", [])}
    unresolved_by_title = {title_key(x["title"]): x for x in state.get("unresolved", [])}
    # Repair earlier inventories made before a localized namespace was known.
    for item in inventory_by_title.values():
        namespace=item['title'].split(':',1)[0].casefold()
        if namespace in ALLOWED_NAMESPACES:item['namespace_id']=ALLOWED_NAMESPACES[namespace]
        elif namespace in EXPLICIT_NAMESPACES:item['namespace_id']=EXPLICIT_NAMESPACES[namespace]
        elif title_key(item['title']) in CITE_LABEL_KEYS:item['namespace_id']=8
    for key,item in list(unresolved_by_title.items()):
        if item['reason']=='namespace-not-allowed' and (_namespace_ok(item['title']) or key in allowed_titles):
            state.setdefault('prior_unresolved',[]).append(item)
            del unresolved_by_title[key];visited.discard(key);queue.append(item['title'])
    edges: dict[str, list[str]] = state.get("edges", {root_title: initial})
    # A resumed closure can gain newly recognized literal Lua/redirect edges
    # without discarding its acquired source records or retrying old failures.
    for title,text in [(root_title,root_text),*((item['title'],item['content']) for item in state.get('supporting',[]) if isinstance(item.get('content'),str))]:
        children=dependency_names(text);edges[title]=children
        for child in children:
            if title_key(child) not in visited and child not in queue:queue.append(child)
    requests_made = int(state.get("requests_made", 0))
    budget_exceeded = False
    interrupted_by_rate_limit = False

    def checkpoint(current_queue=None):
        if progress_path:
            state.update({"title_key_version":3,"allowed_titles":sorted(allowed_titles),"pending": list(current_queue if current_queue is not None else queue),
                          "visited": sorted(visited), "supporting": list(inventory_by_title.values()),
                          "unresolved": list(unresolved_by_title.values()), "edges": edges,
                          "requests_made": requests_made})
            atomic_json(progress_path, state)

    while queue:
        title = queue.popleft()
        folded = title_key(title)
        if folded in visited:
            continue
        if len(visited) >= max_pages:
            queue.appendleft(title)
            budget_exceeded = True
            break
        if not _namespace_ok(title) and folded not in allowed_titles:
            unresolved_by_title[folded] = {"title": title, "reason": "namespace-not-allowed"}
            visited.add(folded)
            checkpoint()
            continue
        if request_budget is not None and request_budget[0] <= 0:
            queue.appendleft(title)
            budget_exceeded = True
            break
        if request_budget is not None:
            request_budget[0] -= 1
        requests_made += 1
        # Record that the request was started before the network call. A crash or rate
        # limit therefore leaves the current title available for an explicit resume.
        queue.appendleft(title)
        checkpoint()
        queue.popleft()
        try:
            result = resolver(title, cutoff)
        except Exception as e:
            message = str(e)
            if "429" in message or "retry limit" in message or "maxlag" in message.casefold():
                queue.appendleft(title)
                interrupted_by_rate_limit = True
                checkpoint()
                break
            unresolved_by_title[folded] = {"title": title, "reason": f"source-error:{type(e).__name__}", "detail": message[:400]}
            visited.add(folded)
            checkpoint()
            continue
        if not result:
            unresolved_by_title[folded] = {"title": title, "reason": "missing-at-cutoff"}
            visited.add(folded)
            checkpoint()
            continue
        if result.get("timestamp") and result["timestamp"] > cutoff:
            unresolved_by_title[folded] = {"title": title, "reason": "resolver-returned-version-after-cutoff"}
            visited.add(folded)
            checkpoint()
            continue
        text = result.get("content")
        if not isinstance(text, str):
            unresolved_by_title[folded] = {"title": title, "reason": "content-hidden-or-unavailable"}
            visited.add(folded)
            checkpoint()
            continue
        canonical_title = result.get("title") or title
        children = dependency_names(text)
        edges[canonical_title] = children
        namespace = canonical_title.split(":", 1)[0].casefold()
        inventory_by_title[folded] = {"title": canonical_title, "source_revision_id": result.get("source_revision_id"),
                                      "source_page_id": result.get("source_page_id"), "source_parent_id": result.get("source_parent_id"),
                                      "timestamp": result.get("timestamp"), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                      "namespace": namespace, "namespace_id": ALLOWED_NAMESPACES.get(namespace, namespace_ids.get(namespace, EXPLICIT_NAMESPACES.get(namespace, 8 if title_key(canonical_title) in CITE_LABEL_KEYS else 0 if ":" not in canonical_title else None))), "content": text,
                                      "content_model": result.get("content_model"), "content_format": result.get("content_format"),
                                      "source_sha1": result.get("source_sha1"), "author": result.get("author"),
                                      "comment": result.get("comment"), "comment_hidden": result.get("comment_hidden", False),
                                      "minor": result.get("minor", False), "content_hidden": result.get("content_hidden", False),
                                      "source_url": result.get("source_url"), "acquisition_method": result.get("acquisition_method"),
                                      "acquired_at": result.get("acquired_at"), "anchor_revision_id": result.get("source_revision_id")}
        unresolved_by_title.pop(folded, None)
        visited.add(folded)
        for child in children:
            if title_key(child) not in visited:
                queue.append(child)
        checkpoint()
    # Report cycles explicitly; traversal terminates even when dependencies loop.
    visiting: set[str] = set()
    visited_dfs: set[str] = set()
    cycles: list[list[str]] = []
    keyed_edges = {title_key(title): children for title, children in edges.items()}
    def walk(node: str, stack: list[str]) -> None:
        key = title_key(node)
        if key in visiting:
            start = next((i for i, x in enumerate(stack) if title_key(x) == key), 0)
            cycles.append(stack[start:] + [node])
            return
        if key in visited_dfs:
            return
        visiting.add(key)
        for child in keyed_edges.get(key, []):
            walk(child, stack + [node])
        visiting.remove(key)
        visited_dfs.add(key)
    walk(root_title, [])
    unresolved = list(unresolved_by_title.values())
    if queue:
        unresolved.extend({"title": title, "reason": "request-budget-exceeded" if budget_exceeded else "pending-resume"} for title in queue)
    if interrupted_by_rate_limit:
        unresolved.append({"title": root_title, "reason": "source-rate-limited-checkpointed"})
    output = {"schema_version": 1, "root_title": root_title, "cutoff": cutoff,
              "supporting": sorted(inventory_by_title.values(), key=lambda x: x["title"].casefold()),
              "unresolved": unresolved, "cycles": cycles, "requests_made": requests_made,
              "pending": list(queue), "budget_exceeded": budget_exceeded,
              "interrupted_by_rate_limit": interrupted_by_rate_limit,
              "complete": not unresolved and not cycles and not queue}
    checkpoint(queue)
    return output


def source_support_resolver(language: str, *, api: Callable = fetch_json,
                            sleep: Callable = time.sleep, interval: float = 1.0) -> Callable[[str, str], dict[str, Any] | None]:
    def resolve(title: str, cutoff: str) -> dict[str, Any] | None:
        params = {"action": "query", "format": "json", "formatversion": 2,
                  "prop": "info|revisions", "titles": title,
                  "rvprop": "ids|timestamp|user|userid|comment|flags|content|sha1|contentmodel|contentformat",
                  "rvslots": "main", "rvlimit": "1", "rvdir": "older", "rvstart": normalize_timestamp(cutoff)}
        url = API.format(lang=language) + "?" + urllib.parse.urlencode(params)
        sleep(interval)
        response = api(url, retries=1, wait_on_rate_limit=False) if api is fetch_json else api(url)
        pages = response.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") is not None:
            return None
        page = pages[0]
        revisions = page.get("revisions", [])
        if not revisions:
            return None
        raw = revisions[0]
        synthetic_article = {"source_wiki": f"{language}wiki", "language": language,
                             "source_page_id": page.get("pageid"), "anchor_revision_id": raw.get("revid")}
        record = revision_record(raw, synthetic_article)
        return {"title": page.get("title", title), "source_page_id": page.get("pageid"),
                "source_revision_id": record["source_revision_id"], "source_parent_id": record["source_parent_id"],
                "timestamp": record["timestamp"], "content": record["content"],
                "content_hidden": record["content_hidden"], "author": record["author"],
                "comment": record["comment"], "comment_hidden": record["comment_hidden"],
                "minor": record["minor"], "content_model": record["content_model"],
                "content_format": record["content_format"], "source_sha1": record["source_sha1"],
                "computed_sha1": record["computed_sha1"], "computed_sha256": record.get("computed_sha256"),
                "source_url": f"https://{language}.wikipedia.org/?oldid={record['source_revision_id']}",
                "acquisition_method": "mediawiki-api-support", "acquired_at": record["acquired_at"],
                "anchor_revision_id": record["source_revision_id"]}
    return resolve


def acquire_support_corpus(corpus_path: Path, anchor_report_path: Path, output_dir: Path,
                           *, api: Callable = fetch_json, sleep: Callable = time.sleep,
                           interval: float = 1.0, max_pages: int = 1000,
                           max_requests: int = 50) -> dict[str, Any]:
    corpus = validate_corpus(read_json(corpus_path))
    if corpus["scope"] != "sample":
        raise DataError("support dependency spike is sample-only; full support acquisition requires an explicit later run")
    spike = read_json(anchor_report_path)
    if spike.get("scope") != "sample-anchor-spike" or not spike.get("complete"):
        raise DataError("a successful real sample anchor-spike report is required before support traversal")
    results = []
    request_budget = [max_requests]
    for page in spike["pages"]:
        article = next((x for x in corpus["articles"] if x["source_wiki"] == page["source_wiki"] and x["source_page_id"] == page["source_page_id"]), None)
        if article is None:
            raise DataError(f"anchor spike includes a page absent from sample manifest: {page['source_wiki']}:{page['source_page_id']}")
        root = page.get("anchor_record")
        if not isinstance(root, dict) or root.get("content") is None:
            raise DataError(f"sample root text is unavailable for {article['source_wiki']}:{article['source_page_id']}")
        resolver = source_support_resolver(article["language"], api=api, sleep=sleep, interval=interval)
        target = output_dir / article["source_wiki"] / f"{article['source_page_id']}.json"
        progress = target.with_suffix(".progress.json")
        inventory = discover_support(article["title"], root["content"], root["timestamp"], resolver,
                                     max_pages=max_pages, progress_path=progress, request_budget=request_budget)
        atomic_json(target, inventory)
        results.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"],
                        "root_title": article["title"], "supporting_pages": len(inventory["supporting"]),
                        "unresolved_count": len(inventory["unresolved"]), "cycle_count": len(inventory["cycles"]),
                        "requests_made": inventory["requests_made"], "pending_count": len(inventory["pending"]),
                        "budget_exceeded": inventory["budget_exceeded"], "interrupted_by_rate_limit": inventory["interrupted_by_rate_limit"],
                        "complete": inventory["complete"], "manifest": str(target), "checkpoint": str(progress)})
        sleep(interval)
    return {"schema_version": 1, "scope": "sample", "results": results,
            "supporting_pages": sum(x["supporting_pages"] for x in results),
            "unresolved_count": sum(x["unresolved_count"] for x in results),
            "request_budget": max_requests, "requests_used": max_requests - request_budget[0],
            "budget_exhausted": request_budget[0] <= 0,
            "complete": all(x["complete"] for x in results)}
