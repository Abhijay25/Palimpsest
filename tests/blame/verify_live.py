"""Assert synthetic fixture outcomes against the real Blame Action API.

This verifier requires the root-owned, already-running feature runtime and a
state file from seed_synthetic.py. It does not manage Docker or suppress a
missing extension/API as a skip.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

from mediawiki_api import MediaWikiApiError, WikiApi
from seed_synthetic import FIXTURE_IDS, LANGS, load_manifest, fixture, DOCKER_PROJECT


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def utf16_slice(text: str, start: int, end: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[start * 2:end * 2].decode("utf-16-le")


def validate_analyze_schema(result: dict) -> list[str]:
    """Validate an ordinary ready response before semantic or negative checks."""
    errors = []
    required = {"schema_version", "status", "page", "snapshot", "coverage", "source_text", "html", "spans", "revisions", "events", "algorithm", "mapping"}
    missing = required - set(result)
    if missing:
        errors.append("missing keys: " + ", ".join(sorted(missing)))
        return errors
    if result["schema_version"] != 1 or result["status"] != "ready":
        errors.append(f"ordinary analyze response must be schema v1 ready; got v{result['schema_version']} {result['status']}")
    if not isinstance(result["source_text"], str) or not isinstance(result["html"], str):
        errors.append("source_text and html must be strings")
    if not isinstance(result["spans"], list) or not isinstance(result["revisions"], list) or not isinstance(result["events"], list):
        errors.append("spans, revisions and events must be arrays")
    return errors


def extension_result(api: WikiApi, title: str, revision_id: int, ranges: list[dict] | None = None) -> dict:
    values: dict[str, object] = {
        "action": "palimpsestblame",
        "op": "analyze",
        "title": title,
        "revision": revision_id,
    }
    if ranges is not None:
        values["ranges"] = json.dumps(ranges, separators=(",", ":"))
    response = api.call(values)
    result = response.get("palimpsestblame")
    if not isinstance(result, dict):
        raise AssertionError("action=palimpsestblame returned no palimpsestblame result object")
    return result


def id_by_alias(page_state: dict) -> dict[str, int]:
    return {row["alias"]: row["revision_id"] for row in page_state["revisions"]}


def assert_spans(result: dict, expected_segments: list[dict], ids: dict[str, int]) -> None:
    source = result["source_text"]
    spans = result["spans"]
    for span in spans:
        if not all(key in span for key in ("start", "end", "revision_id", "token_id", "lineage_ids")):
            raise AssertionError("a span lacks UTF-16 range, local revision, stable token ID or lineage IDs")
        if not (0 <= span["start"] < span["end"] <= utf16_length(source)):
            raise AssertionError(f"span has invalid UTF-16 range {span['start']}..{span['end']}")
        token_pattern = rf"^{span['revision_id']}:\d+$"
        if not isinstance(span["token_id"], str) or not re.fullmatch(token_pattern, span["token_id"]):
            raise AssertionError("token_id must be a stable token ID shaped local-revision-id:zero-based-token-index")
        if not isinstance(span["lineage_ids"], list) or any(
            not isinstance(token, str) or not re.fullmatch(r"^\d+:\d+$", token)
            for token in span["lineage_ids"]
        ):
            raise AssertionError("lineage_ids must contain stable local-revision-id:token-index strings")
        if "token_ranges" in span:
            ranges = span["token_ranges"]
            if not isinstance(ranges, list) or not ranges:
                raise AssertionError("token_ranges must be a non-empty array when present")
            previous_end = span["start"]
            token_ids = []
            for token_range in ranges:
                if not isinstance(token_range, list) or len(token_range) != 3:
                    raise AssertionError("each token_ranges entry must be [start, end, stable_token_id]")
                start, end, token_id = token_range
                if not isinstance(start, int) or not isinstance(end, int) or not (span["start"] <= start < end <= span["end"]):
                    raise AssertionError("token_ranges entry has invalid UTF-16 bounds outside its coalesced span")
                if start < previous_end:
                    raise AssertionError("token_ranges entries must be ordered and non-overlapping")
                if not isinstance(token_id, str) or not re.fullmatch(token_pattern, token_id):
                    raise AssertionError("token_ranges stable token ID must belong to the span's local revision")
                token_ids.append(token_id)
                previous_end = end
            if token_ids[0] != span["token_id"]:
                raise AssertionError("coalesced span token_id must be the first token_ranges stable ID")
            if any(token_id not in span["lineage_ids"] for token_id in token_ids):
                raise AssertionError("lineage_ids must include every token ID represented by a coalesced span")
    for segment in expected_segments:
        start, end = segment["start"], segment["end"]
        expected_id = ids[segment["revision"]]
        if utf16_slice(source, start, end) != segment["text"]:
            raise AssertionError(f"independent fixture range no longer matches {segment['text']!r}")
        cursor = start
        overlapping = sorted((s for s in spans if s["start"] < end and s["end"] > start), key=lambda s: (s["start"], s["end"]))
        for span in overlapping:
            if span["start"] > cursor:
                break
            if span["revision_id"] != expected_id:
                raise AssertionError(f"{segment['text']!r} includes unexpected revision {span['revision_id']}, expected {expected_id}")
            if not any(token.startswith(f"{expected_id}:") for token in span["lineage_ids"]):
                raise AssertionError(f"{segment['text']!r} lacks expected stable lineage from revision {expected_id}")
            if "token_ranges" in span:
                ranges = sorted((row[0], row[1]) for row in span["token_ranges"] if row[0] < end and row[1] > start)
            else:
                ranges = [(span["start"], span["end"])]
            for range_start, range_end in ranges:
                if range_start > cursor:
                    break
                cursor = max(cursor, min(end, range_end))
        if cursor < end:
            raise AssertionError(f"{segment['text']!r} is not fully attributed to local revision {expected_id}")


def event_signature(event: dict, ids: dict[str, int]) -> tuple:
    return (event.get("revision_id"), event.get("before"), event.get("after"), bool(event.get("ambiguous")))


def assert_expected_events(actual: list[dict], expected: list[dict], ids: dict[str, int]) -> None:
    wanted = {(ids[row["revision"]], row["before"], row["after"], row["ambiguous"]) for row in expected}
    observed = {event_signature(row, ids) for row in actual}
    if not wanted.issubset(observed):
        raise AssertionError(f"missing expected events: {wanted - observed}")
    for fixture_event in expected:
        if "before_range" not in fixture_event:
            continue
        signature = (ids[fixture_event["revision"]], fixture_event["before"], fixture_event["after"], fixture_event["ambiguous"])
        event = next(row for row in actual if event_signature(row, ids) == signature)
        before_start, before_end = fixture_event["before_range"]
        if (event.get("old_start"), event.get("old_end")) != (before_start, before_end):
            raise AssertionError(f"event {signature} source deletion/replacement offsets differ from independent fixture ranges")
        after_range = fixture_event["after_range"]
        expected_after = tuple(after_range) if after_range is not None else (None, None)
        if (event.get("new_start"), event.get("new_end")) != expected_after:
            raise AssertionError(f"event {signature} target replacement offsets differ from independent fixture ranges")


def call_selection(api: WikiApi, title: str, revision_id: int, selection: dict) -> dict:
    ranges = [{"start": selection["start"], "end": selection["end"]}]
    result = extension_result(api, title, revision_id, ranges)
    errors = validate_analyze_schema(result)
    if errors:
        raise AssertionError("ordinary selected analyze schema invalid: " + "; ".join(errors))
    if result["selection"]["ranges"] != ranges:
        raise AssertionError("backend changed or dropped the exact requested UTF-16 selection range")
    return result


def verify_history(api: WikiApi, page_state: dict, fixture_id: str) -> dict:
    doc = fixture(fixture_id)
    expected = doc["expected"]
    ids = id_by_alias(page_state)
    title = page_state["title"]
    final_revision = ids[expected["snapshot"]]
    started = time.perf_counter()
    ordinary = extension_result(api, title, final_revision)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    schema_errors = validate_analyze_schema(ordinary)
    if schema_errors:
        raise AssertionError("ordinary analyze schema invalid: " + "; ".join(schema_errors))
    if ordinary["source_text"] != doc["revisions"][-1]["text"]:
        raise AssertionError("blame source_text does not equal the seeded local revision text")
    if ordinary["snapshot"].get("revision_id") != final_revision:
        raise AssertionError("content and attribution snapshot local revision IDs differ")
    repeated = extension_result(api, title, final_revision)
    if [(span.get("token_id"), span.get("lineage_ids")) for span in ordinary["spans"]] != [
        (span.get("token_id"), span.get("lineage_ids")) for span in repeated["spans"]
    ]:
        raise AssertionError("token and lineage IDs changed across identical analyze requests")

    performance = doc.get("performance_case")
    if performance:
        token_count = len(ordinary["source_text"].split())
        if token_count < performance["minimum_token_count"]:
            raise AssertionError(f"performance fixture had only {token_count} tokens")
        if token_count != expected["token_count"]:
            raise AssertionError(f"performance fixture token count changed: {token_count}")
    else:
        token_count = len(ordinary["source_text"].split())
    response_bytes = len(json.dumps(ordinary, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if response_bytes > 2 * 1024 * 1024:
        raise AssertionError(f"analyze response exceeded the 2 MiB budget: {response_bytes} bytes")

    if "last_change_segments" in expected:
        assert_spans(ordinary, expected["last_change_segments"], ids)
    if "events" in expected:
        assert_expected_events(ordinary["events"], expected["events"], ids)

    if "selection" in expected:
        selected = call_selection(api, title, final_revision, expected["selection"])
        actual_selection = selected["selection"]
        expected_contributors = {ids[alias] for alias in expected["selection"].get("contributors", [])}
        actual_contributors = set(actual_selection.get("revision_ids", []))
        if not expected_contributors.issubset(actual_contributors):
            raise AssertionError(f"selection omitted contributors {expected_contributors - actual_contributors}")
        if expected["selection"].get("complete") and actual_selection.get("reasons"):
            raise AssertionError("fully mapped synthetic selection was reported incomplete: " + "; ".join(actual_selection["reasons"]))
        if "ambiguity" in expected:
            if not actual_selection.get("ambiguous"):
                raise AssertionError("repeated/moved/reverted wording was presented as unambiguous")
            assert_expected_events(
                actual_selection.get("events", []),
                expected["selection"].get("events", expected["events"]),
                ids,
            )
        elif "events" in expected:
            assert_expected_events(actual_selection.get("events", []), expected["events"], ids)
        for excluded_alias in expected.get("excluded_from_selection_timeline", []):
            excluded_id = ids[excluded_alias]
            if any(event.get("revision_id") == excluded_id for event in actual_selection.get("events", [])):
                raise AssertionError(f"unrelated later edit {excluded_id} leaked into selected statement timeline")
    return {
        "elapsed_ms": elapsed_ms,
        "tokens": token_count,
        "source_bytes": len(ordinary["source_text"].encode("utf-8")),
        "response_bytes": response_bytes,
    }


def verify_dates(api: WikiApi, page_state: dict) -> None:
    """Check real API inclusivity on seeded revisions; fixture ties remain pure ground truth."""
    ids = id_by_alias(page_state)
    revision_id = ids["r3"]
    analyzed = extension_result(api, page_state["title"], revision_id)
    errors = validate_analyze_schema(analyzed)
    if errors:
        raise AssertionError("ordinary date fixture schema invalid: " + "; ".join(errors))
    rows = analyzed["revisions"]
    by_id = {row["revision_id"]: row for row in rows}
    if not set(ids.values()).issubset(by_id):
        raise AssertionError("analyze history does not contain every seeded local revision")
    timestamps = {rev_id: by_id[rev_id]["timestamp"] for rev_id in ids.values()}
    oldest = min(timestamps.values())
    latest = max(timestamps.values())
    check = api.call({
        "action": "palimpsestblame", "op": "versions", "title": page_state["title"],
        "mode": "range", "from": oldest, "to": latest, "limit": 100,
    }).get("palimpsestblame")
    if not isinstance(check, dict) or check.get("status") != "ready":
        raise AssertionError("versions range did not return a ready result")
    got = [row["revision_id"] for row in check.get("versions", [])]
    expected_order = sorted(ids.values(), key=lambda rev_id: (timestamps[rev_id], rev_id), reverse=True)
    if got != expected_order:
        raise AssertionError(f"inclusive date range/order mismatch: got {got}, expected {expected_order}")
    before_oldest = api.call({
        "action": "palimpsestblame", "op": "versions", "title": page_state["title"],
        "mode": "asof", "to": "1900-01-01T00:00:00Z", "limit": 100,
    }).get("palimpsestblame")
    if not isinstance(before_oldest, dict) or before_oldest.get("selected_revision_id") is not None:
        raise AssertionError("as-of before earliest history silently selected a later revision")

    # Ordinary schema and a positive query are checked before invalid-input
    # expectations, so parser/parameter failures cannot masquerade as a guard.
    invalid_mode = dict(title=page_state["title"], mode="nonsense", limit=100)
    try:
        invalid_response = api.call({
            "action": "palimpsestblame", "op": "versions", **invalid_mode,
        })
    except MediaWikiApiError as exc:
        if "mode" not in (exc.code + " " + exc.info).lower():
            raise AssertionError("invalid mode failed for an unrelated API reason") from exc
    else:
        result = invalid_response.get("palimpsestblame", {})
        if result.get("status") != "failed" or result.get("reason") != "unsupported_mode":
            raise AssertionError("unsupported version mode was accepted or returned the wrong failure reason")

    try:
        reversed_range = api.call({
            "action": "palimpsestblame", "op": "versions", "title": page_state["title"],
            "mode": "range", "from": "2027-01-01T00:00:00Z", "to": "1900-01-01T00:00:00Z", "limit": 100,
        })
    except MediaWikiApiError as exc:
        if "range" not in (exc.code + " " + exc.info).lower() and "bound" not in (exc.code + " " + exc.info).lower():
            raise AssertionError("reversed date range failed for an unrelated API reason") from exc
    else:
        result = reversed_range.get("palimpsestblame", {})
        if result.get("status") != "unavailable" or result.get("reason") != "invalid-or-reversed-range":
            raise AssertionError("reversed date range was accepted or returned the wrong failure reason")

    invalid_bound = api.call({
        "action": "palimpsestblame", "op": "versions", "title": page_state["title"],
        "mode": "asof", "to": "2026-03-15T12:99:00Z", "limit": 100,
    }).get("palimpsestblame")
    if not isinstance(invalid_bound, dict) or invalid_bound.get("status") != "unavailable" or invalid_bound.get("reason") != "invalid-date-bound":
        raise AssertionError("invalid UTC bound was accepted or returned the wrong failure reason")


def verify_cache_invalidation(api_url: str, page_state: dict, auth: dict, run_id: str) -> dict:
    """Warm a synthetic result, make a real local edit, then prove cache refresh."""
    title = page_state["title"]
    old_id = page_state["revisions"][-1]["revision_id"]
    before = extension_result(WikiApi(api_url), title, old_id)
    schema_errors = validate_analyze_schema(before)
    if schema_errors:
        raise AssertionError("ordinary page failed schema validation before cache invalidation: " + "; ".join(schema_errors))
    before_text = before["source_text"]
    probe = f"cacheprobe{run_id}"
    new_text = before_text + " " + probe
    editor = WikiApi(api_url)
    editor.login(auth["username"], auth["password"])
    new_id = editor.edit(title, new_text, f"[synthetic Blame cache invalidation {run_id}]")
    refreshed = extension_result(WikiApi(api_url), title, new_id)
    errors = validate_analyze_schema(refreshed)
    if errors:
        raise AssertionError("post-edit analyze schema invalid: " + "; ".join(errors))
    if refreshed["snapshot"].get("revision_id") != new_id or refreshed["source_text"] != new_text:
        raise AssertionError("analyze cache did not refresh to the new local revision and content")
    start = utf16_length(before_text) + 1
    assert_spans(refreshed, [{"text": probe, "revision": "local", "start": start, "end": start + len(probe)}], {"local": new_id})
    prior = extension_result(WikiApi(api_url), title, old_id)
    if prior["snapshot"].get("revision_id") != old_id or prior["source_text"] != before_text:
        raise AssertionError("cache refresh mutated the earlier immutable revision snapshot")
    return {"previous_revision_id": old_id, "new_revision_id": new_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    parser.add_argument("--confirm-project", required=True)
    args = parser.parse_args()
    if args.confirm_project != DOCKER_PROJECT:
        parser.error(f"--confirm-project must be {DOCKER_PROJECT}")
    try:
        manifest = load_manifest(args.manifest)
        state = json.loads(args.state_file.read_text(encoding="utf-8"))
        auth = json.loads(args.auth_file.read_text(encoding="utf-8"))
        if state.get("scope") != "synthetic_only" or state.get("project") != DOCKER_PROJECT:
            raise ValueError("state file is not an authorized synthetic-only feature fixture")
        if auth.get("scope") != "synthetic_test_accounts_only" or auth.get("project") != DOCKER_PROJECT or auth.get("run_id") != state.get("run_id"):
            raise ValueError("credentials do not match this synthetic fixture run")
        results = []
        for language in LANGS:
            expected_url = manifest["languages"][language]["api_url"]
            language_state = state["languages"][language]
            if language_state["api_url"] != expected_url:
                raise ValueError(f"state API URL differs from root manifest for {language}")
            api = WikiApi(expected_url)
            for fixture_id in FIXTURE_IDS:
                page_state = language_state["pages"][fixture_id]
                metrics = verify_history(api, page_state, fixture_id)
                if fixture_id == "date_boundaries":
                    verify_dates(api, page_state)
                suffix = (
                    f" tokens={metrics['tokens']} source_bytes={metrics['source_bytes']}"
                    f" response_bytes={metrics['response_bytes']} analyze_ms={metrics['elapsed_ms']}"
                    if fixture_id == "large_unique_anchor_history" else ""
                )
                results.append(f"PASS {language}/{fixture_id}{suffix}")
            cache_state = verify_cache_invalidation(
                language_state["api_url"],
                language_state["pages"]["cross_contributor_deletion"],
                auth["languages"][language],
                state["run_id"],
            )
            results.append(f"PASS {language}/local-edit-cache-invalidation {cache_state['previous_revision_id']}→{cache_state['new_revision_id']}")
        print("\n".join(results))
    except (OSError, ValueError, KeyError, TypeError, MediaWikiApiError, AssertionError) as exc:
        print(f"FAIL live Blame acceptance: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
