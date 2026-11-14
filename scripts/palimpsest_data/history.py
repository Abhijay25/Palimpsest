from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .io import DataError, atomic_json, atomic_write, canonical_json, iter_jsonl, read_json, sha256_bytes, sha256_file
from .manifests import WIKIS, validate_corpus

API = "https://{lang}.wikipedia.org/w/api.php"
MAX_RETRIES = 5
MAX_REVISION_BATCH = 5


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_timestamp(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as e:
        raise DataError(f"invalid source timestamp {value!r}") from e
    if parsed.tzinfo is None:
        raise DataError(f"source timestamp has no timezone: {value!r}")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _retry_after(headers) -> float | None:
    value = headers.get("Retry-After") if headers else None
    try:
        return max(0.0, min(float(value), 60.0))
    except (TypeError, ValueError):
        return None


def fetch_json(url: str, *, opener: Callable = urllib.request.urlopen,
               sleep: Callable = time.sleep, retries: int = MAX_RETRIES,
               jitter: Callable = random.random, wait_on_rate_limit: bool = True) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Palimpsest/1.0 (public-history importer)", "Accept": "application/json"})
            with opener(req, timeout=60) as response:
                body = response.read()
                status = getattr(response, "status", 200)
                if status >= 500 or status == 429:
                    raise urllib.error.HTTPError(url, status, "transient source response", response.headers, None)
            try:
                data = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise DataError(f"source returned invalid JSON: {e}") from e
            if "error" in data:
                err = data["error"]
                if err.get("code") in {"ratelimited", "maxlag"}:
                    if not wait_on_rate_limit:
                        raise DataError(f"source API {err.get('code')} deferred; lag={err.get('lag', 'unknown')}")
                    delay = min(float(err.get("lag", 1)), 60.0)
                    sleep(delay)
                    continue
                raise DataError(f"MediaWiki API error {err.get('code')}: {err.get('info')}")
            return data
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise DataError(f"source HTTP failure {e.code}") from e
            last = e
            if e.code == 429 and not wait_on_rate_limit:
                raise DataError(f"source HTTP failure 429 deferred; retry-after={_retry_after(e.headers)}") from e
            wait = _retry_after(e.headers) or min(2 ** attempt + jitter(), 30.0)
            sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            sleep(min(2 ** attempt + jitter(), 30.0))
    raise DataError(f"source retry limit ({retries}) exhausted: {last}")


def revision_record(raw: dict[str, Any], article: dict[str, Any], *, acquired_at: str | None = None) -> dict[str, Any]:
    slots = raw.get("slots") or {}
    main = slots.get("main") or raw
    hidden_text = "texthidden" in raw or "texthidden" in main or "contenthidden" in raw
    has_content = "content" in main or "*" in main
    content = main.get("content", main.get("*")) if has_content and not hidden_text else None
    if content is not None and not isinstance(content, str):
        raise DataError(f"revision {raw.get('revid')} has non-text content")
    user_hidden = "userhidden" in raw
    user = raw.get("user")
    author_kind = "unknown" if user is None else ("anonymous" if raw.get("anon") is not None else "named")
    comment_hidden = "commenthidden" in raw
    comment = None if comment_hidden else raw.get("comment")
    revision_id = raw.get("revid")
    if type(revision_id) is not int or revision_id <= 0:
        raise DataError("source revision has invalid/missing revid")
    parent_id = raw.get("parentid", 0)
    parent_id = parent_id if type(parent_id) is int and parent_id > 0 else None
    timestamp = normalize_timestamp(raw.get("timestamp"))
    source_sha1 = main.get("sha1", raw.get("sha1"))
    computed_sha1 = None
    if content is not None:
        computed_sha1 = hashlib.sha1(content.encode("utf-8")).hexdigest()
        if source_sha1 and source_sha1 != computed_sha1:
            raise DataError(f"source sha1 mismatch for revision {raw.get('revid')}")
    base = {
        "source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"],
        "source_revision_id": revision_id, "source_parent_id": parent_id, "timestamp": timestamp,
        "author": {"kind": author_kind, "value": None if user_hidden else user, "hidden": user_hidden},
        "comment": comment, "comment_hidden": comment_hidden, "minor": "minor" in raw,
        "content_model": main.get("contentmodel") or raw.get("contentmodel"), "content_format": main.get("contentformat") or raw.get("contentformat"),
        "content": content, "content_hidden": hidden_text, "source_sha1": source_sha1, "computed_sha1": computed_sha1,
        "source_url": f"https://{article['language']}.wikipedia.org/?oldid={revision_id}",
        "acquisition_method": "mediawiki-api", "acquired_at": acquired_at or utc_now(),
        "anchor_revision_id": article["anchor_revision_id"],
    }
    if content is not None:
        base["computed_sha256"] = sha256_bytes(content.encode("utf-8"))
    return base


def _page_dir(history_dir: Path, article: dict[str, Any]) -> Path:
    return history_dir / article["source_wiki"] / str(article["source_page_id"])


def iter_page_records(history_dir: Path, article: dict[str, Any]):
    """Stream only checkpoint-committed records, validating every batch on read."""
    page_dir = _page_dir(history_dir, article)
    state_path = page_dir / "state.json"
    if not state_path.exists():
        return
    state = read_json(state_path)
    for batch in state.get("committed_batches", []):
        name = batch.get("path", "")
        if Path(name).name != name or not name.startswith("batch-") or not name.endswith(".jsonl"):
            raise DataError(f"invalid committed batch path for {article['source_wiki']}:{article['source_page_id']}")
        path = page_dir / name
        if not path.exists() or sha256_file(path) != batch.get("sha256"):
            raise DataError(f"committed source batch checksum mismatch: {path}")
        count = 0
        for record in iter_jsonl([path]):
            count += 1
            yield record
        if count != batch.get("count"):
            raise DataError(f"committed source batch record count mismatch: {path}")


def _records_for_page(history_dir: Path, article: dict[str, Any]) -> list[dict[str, Any]]:
    return list(iter_page_records(history_dir, article))


def _orphan_records(path: Path, article: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(iter_jsonl([path]))
    seen = set()
    for row in rows:
        if row.get("source_wiki") != article["source_wiki"] or row.get("source_page_id") != article["source_page_id"]:
            raise DataError(f"orphan batch has mismatched source identity: {path}")
        rev = row.get("source_revision_id")
        if type(rev) is not int or rev <= 0 or rev in seen:
            raise DataError(f"orphan batch has invalid or duplicate revision identity: {path}")
        seen.add(rev)
    return rows


def _identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(k) for k in ("source_wiki", "source_page_id", "source_revision_id", "source_parent_id", "timestamp", "author", "comment", "comment_hidden", "minor", "content_model", "content_format", "content_hidden", "source_sha1", "computed_sha1", "computed_sha256", "anchor_revision_id"))


def _analyze_gaps(state: dict[str, Any], history_dir: Path, article: dict[str, Any]) -> None:
    ids = set()
    for record in iter_page_records(history_dir, article):
        ids.add(record["source_revision_id"])
    existing = {(g.get("kind"), g.get("source_revision_id"), g.get("source_parent_id")) for g in state.get("unresolved_gaps", [])}
    for record in iter_page_records(history_dir, article):
        if record["content"] is None:
            gap = ("revision-text-unavailable", record["source_revision_id"], None)
            if gap not in existing:
                state["unresolved_gaps"].append({"kind": gap[0], "source_revision_id": gap[1], "hidden": record["content_hidden"]})
                existing.add(gap)
        parent = record["source_parent_id"]
        if parent is not None and parent not in ids:
            gap = ("parent-not-acquired", record["source_revision_id"], parent)
            if gap not in existing:
                state["unresolved_gaps"].append({"kind": gap[0], "source_revision_id": gap[1], "source_parent_id": parent})
                existing.add(gap)
    state["gap_analysis_complete"] = True


def _save_batch(path: Path, records: list[dict[str, Any]]) -> str:
    raw = b"".join(canonical_json(r) + b"\n" for r in records)
    digest = sha256_bytes(raw)
    if path.exists():
        if sha256_file(path) != digest:
            raise DataError(f"conflicting source revision batch at {path}")
    else:
        atomic_write(path, raw)
    return digest


def acquire_article(article: dict[str, Any], history_dir: Path, *, api: Callable = fetch_json,
                    sleep: Callable = time.sleep, interval: float = 1.0) -> dict[str, Any]:
    wiki = article["source_wiki"]
    page_dir = history_dir / wiki / str(article["source_page_id"])
    page_dir.mkdir(parents=True, exist_ok=True)
    state_path = page_dir / "state.json"
    state = read_json(state_path) if state_path.exists() else {
        "schema_version": 1, "source_wiki": wiki, "source_page_id": article["source_page_id"],
        "anchor_revision_id": article["anchor_revision_id"], "continuation": None,
        "committed_batches": [], "anchor_validated": False, "enumeration_exhausted": False,
        "unresolved_gaps": [], "seen_continuations": [], "gap_analysis_complete": False,
    }
    if state["anchor_revision_id"] != article["anchor_revision_id"]:
        raise DataError(f"checkpoint anchor mismatch for {wiki}:{article['source_page_id']}; use a separate corpus data root")
    # A batch file can become durable immediately before a crash and the checkpoint
    # rename can be missed. Recover it only after validating bytes, page identity and
    # revision uniqueness, and persist that explicit recovery in state.
    recorded = {item["path"] for item in state.get("committed_batches", [])}
    for orphan in sorted(page_dir.glob("batch-*.jsonl")):
        if orphan.name in recorded:
            continue
        try:
            rows = _orphan_records(orphan, article)
            checksum = sha256_file(orphan)
        except DataError as e:
            state.setdefault("unresolved_gaps", []).append({"kind": "orphan-batch-invalid", "path": orphan.name, "reason": str(e)})
            atomic_json(state_path, state)
            raise
        batch = {"path": orphan.name, "sha256": checksum, "count": len(rows), "recovered_orphan": True}
        state.setdefault("committed_batches", []).append(batch)
        state.setdefault("recovered_orphans", []).append({"path": orphan.name, "sha256": checksum, "count": len(rows)})
    state["committed_batches"].sort(key=lambda item: item["path"])
    if state["committed_batches"]:
        atomic_json(state_path, state)
    known: dict[int, tuple[Any, ...]] = {}
    for rec in iter_page_records(history_dir, article):
        key = int(rec["source_revision_id"])
        fingerprint = _identity(rec)
        if key in known and known[key] != fingerprint:
            raise DataError(f"conflicting source revision {wiki}:{key}")
        known[key] = fingerprint
    if state["enumeration_exhausted"]:
        if article["anchor_revision_id"] not in known:
            state.setdefault("unresolved_gaps", []).append({"kind": "anchor-missing-from-committed-batches", "anchor_revision_id": article["anchor_revision_id"]})
            atomic_json(state_path, state)
            raise DataError(f"cached history is missing its anchor for {wiki}:{article['source_page_id']}")
        if not state.get("gap_analysis_complete"):
            _analyze_gaps(state, history_dir, article)
            atomic_json(state_path, state)
        return {"state": state, "record_count": len(known)}
    continuation = state.get("continuation")
    anchor_seen = state.get("anchor_validated", False)
    while True:
        params = {
            "action": "query", "format": "json", "formatversion": 2,
            "prop": "revisions", "pageids": str(article["source_page_id"]),
            "rvprop": "ids|timestamp|user|userid|comment|flags|content|sha1|contentmodel|contentformat",
            "rvslots": "main", "rvlimit": str(MAX_REVISION_BATCH), "rvdir": "older",
            "rvstartid": str(article["anchor_revision_id"]),
        }
        if continuation:
            params.update(continuation)
        url = API.format(lang=article["language"]) + "?" + urllib.parse.urlencode(params)
        data = api(url)
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") is not None or pages[0].get("pageid") != article["source_page_id"]:
            state["unresolved_gaps"].append({"kind": "source-page-missing", "source_page_id": article["source_page_id"]})
            atomic_json(state_path, state)
            raise DataError(f"source page {wiki}:{article['source_page_id']} is missing or moved")
        raw_revisions = pages[0].get("revisions", [])
        if not raw_revisions:
            state["unresolved_gaps"].append({"kind": "anchor-not-found", "anchor_revision_id": article["anchor_revision_id"]})
            atomic_json(state_path, state)
            raise DataError(f"anchor {article['anchor_revision_id']} not returned for {wiki}:{article['source_page_id']}")
        parsed = [revision_record(x, article) for x in raw_revisions]
        ids = [x["source_revision_id"] for x in parsed]
        if len(ids) != len(set(ids)):
            raise DataError(f"duplicate source revision IDs in response for {wiki}:{article['source_page_id']}")
        if not anchor_seen:
            if article["anchor_revision_id"] not in ids:
                state["unresolved_gaps"].append({"kind": "anchor-not-found", "anchor_revision_id": article["anchor_revision_id"]})
                atomic_json(state_path, state)
                raise DataError(f"dataset anchor {article['anchor_revision_id']} is not a public revision for {wiki}:{article['source_page_id']}")
            anchor_seen = True
            state["anchor_validated"] = True
        # API rvstartid is a revision boundary, not an identity guarantee. Keep exactly
        # the anchor and older revisions; same-second newer neighbors are excluded by ID.
        anchor_timestamp = article.get("dataset_timestamp")
        if anchor_timestamp:
            anchor_timestamp = normalize_timestamp(anchor_timestamp)
        accepted = []
        for rec in parsed:
            if rec["source_revision_id"] > article["anchor_revision_id"]:
                continue
            if anchor_timestamp and rec["timestamp"] > anchor_timestamp:
                raise DataError(f"revision {rec['source_revision_id']} lies after the selected anchor timestamp")
            if anchor_timestamp and rec["source_revision_id"] == article["anchor_revision_id"] and rec["timestamp"] != anchor_timestamp:
                state["unresolved_gaps"].append({"kind": "anchor-timestamp-mismatch", "revision_id": article["anchor_revision_id"], "dataset_timestamp": anchor_timestamp, "source_timestamp": rec["timestamp"]})
                atomic_json(state_path, state)
                raise DataError("anchor source timestamp does not match locked S dataset timestamp")
            accepted.append(rec)
        if not accepted:
            # A repeated timestamp page can contain only newer neighbors. Do not treat it as exhaustion.
            raise DataError("source response made no progress toward the selected anchor")
        new_batch = []
        for rec in accepted:
            key = rec["source_revision_id"]
            fingerprint = _identity(rec)
            if key in known:
                if known[key] != fingerprint:
                    raise DataError(f"conflicting content for source revision {wiki}:{key}")
                continue
            known[key] = fingerprint
            new_batch.append(rec)
        if new_batch:
            batch_index = len(state["committed_batches"])
            batch_path = page_dir / f"batch-{batch_index:06d}.jsonl"
            digest = _save_batch(batch_path, new_batch)
            state["committed_batches"].append({"path": batch_path.name, "sha256": digest, "count": len(new_batch), "recovered_orphan": False})
        next_cont = data.get("continue")
        state["anchor_validated"] = anchor_seen
        if not next_cont:
            state["continuation"] = None
            state["enumeration_exhausted"] = True
            atomic_json(state_path, state)
            break
        token_key = sha256_bytes(canonical_json(next_cont))
        if token_key in state["seen_continuations"]:
            state["unresolved_gaps"].append({"kind": "repeated-continuation-token", "token_sha256": token_key})
            atomic_json(state_path, state)
            raise DataError(f"repeated continuation token for {wiki}:{article['source_page_id']}")
        state["seen_continuations"].append(token_key)
        state["continuation"] = next_cont
        # Batch bytes are durable before the continuation can advance.
        atomic_json(state_path, state)
        continuation = next_cont
        sleep(interval)
    if article["anchor_revision_id"] not in known:
        state["enumeration_exhausted"] = False
        state["unresolved_gaps"].append({"kind": "anchor-absent-after-exhaustion"})
        atomic_json(state_path, state)
        raise DataError("history exhausted without preserving the anchor revision")
    _analyze_gaps(state, history_dir, article)
    atomic_json(state_path, state)
    return {"state": state, "record_count": len(known)}


def acquire_corpus(corpus_path: Path, history_dir: Path, *, sample_only: bool = False,
                   api: Callable = fetch_json, sleep: Callable = time.sleep, interval: float = 1.0,
                   progress_path: Path | None = None) -> dict[str, Any]:
    corpus = validate_corpus(json.loads(corpus_path.read_text(encoding="utf-8")))
    if corpus["scope"] != "sample" and not sample_only:
        # Full remains explicit: caller must opt in by providing --all-pages.
        raise DataError("full history acquisition requires explicit --all-pages; sample-only is the default guard")
    previous = read_json(progress_path) if progress_path and progress_path.exists() else {}
    saved = {(x.get("source_wiki"), x.get("source_page_id")): x for x in previous.get("articles", [])}
    results = []
    for article in corpus["articles"]:
        try:
            result = acquire_article(article, history_dir, api=api, sleep=sleep, interval=interval)
            results.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "anchor_revision_id": article["anchor_revision_id"], "revisions": result["record_count"], "exhausted": result["state"]["enumeration_exhausted"], "gaps": result["state"]["unresolved_gaps"]})
        except DataError as e:
            page_dir = _page_dir(history_dir, article)
            state_path = page_dir / "state.json"
            state = read_json(state_path) if state_path.exists() else {"schema_version": 1, "source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "anchor_revision_id": article["anchor_revision_id"], "continuation": None, "committed_batches": [], "anchor_validated": False, "enumeration_exhausted": False, "gap_analysis_complete": False, "unresolved_gaps": [], "seen_continuations": []}
            state.setdefault("unresolved_gaps", []).append({"kind": "acquisition-failure", "reason": str(e)})
            atomic_json(state_path, state)
            results.append({"source_wiki": article["source_wiki"], "source_page_id": article["source_page_id"], "anchor_revision_id": article["anchor_revision_id"], "exhausted": False, "error": str(e), "gaps": state["unresolved_gaps"]})
        saved[(article["source_wiki"], article["source_page_id"])] = results[-1]
        progress = {"schema_version": 1, "scope": corpus["scope"], "release": corpus["release"],
                    "articles": [saved[k] for k in sorted(saved)]}
        if progress_path:
            atomic_json(progress_path, progress)
    return {"schema_version": 1, "scope": corpus["scope"], "release": corpus["release"], "articles": results}


def probe_anchor_sample(corpus_path: Path, *, api: Callable = fetch_json,
                        sleep: Callable = time.sleep, interval: float = 1.0) -> dict[str, Any]:
    """Check only the exact S anchor and its immediate public predecessor per sampled page."""
    corpus = validate_corpus(json.loads(corpus_path.read_text(encoding="utf-8")))
    if corpus["scope"] != "sample":
        raise DataError("anchor spike accepts only a deterministic sample manifest")
    pages = []
    for article in corpus["articles"]:
        params = {
            "action": "query", "format": "json", "formatversion": 2,
            "prop": "revisions", "pageids": str(article["source_page_id"]),
            "rvprop": "ids|timestamp|user|userid|comment|flags|content|sha1|contentmodel|contentformat",
            "rvslots": "main", "rvlimit": "2", "rvdir": "older",
            "rvstartid": str(article["anchor_revision_id"]),
        }
        url = API.format(lang=article["language"]) + "?" + urllib.parse.urlencode(params)
        try:
            response = api(url)
            returned = response.get("query", {}).get("pages", [])
            if not returned or returned[0].get("pageid") != article["source_page_id"] or returned[0].get("missing") is not None:
                raise DataError("source page ID is missing/moved")
            raw = returned[0].get("revisions", [])
            records = [revision_record(x, article) for x in raw]
            anchor = next((r for r in records if r["source_revision_id"] == article["anchor_revision_id"]), None)
            if anchor is None:
                raise DataError("FineWiki version does not resolve to a public revision ID on this source page")
            if article.get("dataset_timestamp") and normalize_timestamp(article["dataset_timestamp"]) != anchor["timestamp"]:
                raise DataError(f"dataset timestamp {article['dataset_timestamp']} differs from source timestamp {anchor['timestamp']}")
            if anchor["content"] is None:
                raise DataError("anchor revision text is hidden or unavailable")
            older = [r for r in records if r["source_revision_id"] < article["anchor_revision_id"]]
            pages.append({
                "source_wiki": article["source_wiki"], "language": article["language"],
                "source_page_id": article["source_page_id"], "anchor_revision_id": article["anchor_revision_id"],
                "title": article["title"], "dataset_timestamp": article.get("dataset_timestamp"),
                "source_page_id_matches": True, "anchor_matches": True,
                "anchor_timestamp_matches": not article.get("dataset_timestamp") or anchor["timestamp"] == normalize_timestamp(article["dataset_timestamp"]),
                "public_revisions_returned": len(records), "has_public_predecessor": bool(older),
                "anchor_record": anchor, "predecessor_records": older,
            })
        except DataError as e:
            pages.append({"source_wiki": article["source_wiki"], "language": article["language"],
                          "source_page_id": article["source_page_id"], "anchor_revision_id": article["anchor_revision_id"],
                          "title": article["title"], "verified": False, "error": str(e)})
        sleep(interval)
    by_language = {}
    for lang in ("fi", "sv", "en"):
        lang_pages = [p for p in pages if p["language"] == lang]
        by_language[lang] = {"sampled_pages": len(lang_pages), "anchors_verified": sum(bool(p.get("anchor_matches")) for p in lang_pages),
                             "pages_with_two_public_revisions": sum(bool(p.get("has_public_predecessor")) for p in lang_pages)}
    return {"schema_version": 1, "release": corpus["release"], "scope": "sample-anchor-spike",
            "by_language": by_language, "pages": pages,
            "complete": all(by_language[x]["anchors_verified"] == by_language[x]["sampled_pages"] and by_language[x]["pages_with_two_public_revisions"] > 0 for x in ("fi", "sv", "en"))}


def deterministic_sample(full_manifest: dict[str, Any], per_language: int = 1) -> dict[str, Any]:
    if per_language < 1:
        raise DataError("sample size per language must be positive")
    import hashlib
    articles = []
    for lang in ("fi", "sv", "en"):
        candidates = [a for a in full_manifest["articles"] if a["language"] == lang]
        candidates.sort(key=lambda a: (hashlib.sha256(f"s-2026-10:{a['source_wiki']}:{a['source_page_id']}".encode()).hexdigest(), a["source_page_id"]))
        articles.extend(candidates[:per_language])
    return {"schema_version": 1, "release": full_manifest["release"], "scope": "sample", "expected_counts": {x: per_language for x in ("fi", "sv", "en")}, "articles": articles}
