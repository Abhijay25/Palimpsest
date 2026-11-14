"""Exercise bounded build/status resume and write-API protection on synthetic pages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from mediawiki_api import MediaWikiApiError, WikiApi
from seed_synthetic import LANGS, DOCKER_PROJECT, load_manifest
from verify_live import extension_result, validate_analyze_schema


def action_result(response: dict) -> dict:
    result = response.get("palimpsestblame")
    if not isinstance(result, dict):
        raise AssertionError("Blame job action returned no result object")
    return result


def job_value(result: dict) -> dict:
    job = result.get("job")
    if not isinstance(job, dict):
        raise AssertionError("build/status response omitted the job object")
    if not job.get("id") or job.get("status") not in {"pending", "ready", "failed", "expired"}:
        raise AssertionError("job object lacks an opaque ID or recognized status")
    processed = job.get("processed")
    total = job.get("total")
    if not isinstance(processed, int) or processed < 0:
        raise AssertionError("job processed count must be a non-negative integer")
    if total is not None and (not isinstance(total, int) or total < processed):
        raise AssertionError("job total must be absent or an integer at least as large as processed")
    return job


def request_status(api: WikiApi, title: str, revision_id: int, job_id: str) -> dict:
    return action_result(api.call({
        "action": "palimpsestblame", "op": "status", "title": title,
        "revision": revision_id, "jobid": job_id,
    }))


def assert_ready_cached_history(result: dict, page: dict, target_revision: int) -> str:
    """Check a ready cache against independent text and core revision IDs from seeding."""
    errors = validate_analyze_schema(result)
    if errors:
        raise AssertionError("ready cached analyze schema invalid: " + "; ".join(errors))
    if result["snapshot"].get("revision_id") != target_revision:
        raise AssertionError("ready cached analyze changed the original pinned seed revision")
    expected_text = page.get("expected_text")
    if not isinstance(expected_text, str):
        raise AssertionError("seed state omitted the independent expected source text")
    cached_text = result["source_text"]
    expected_hash = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
    cached_hash = hashlib.sha256(cached_text.encode("utf-8")).hexdigest()
    if cached_hash != expected_hash:
        raise AssertionError("ready cached source_text SHA-256 differs from the seeded target")
    if cached_text != expected_text:
        raise AssertionError("ready cached source_text differs from the seeded target despite matching its SHA-256")

    expected_ids = page.get("revision_ids")
    actual_ids = [revision.get("revision_id") for revision in result["revisions"]]
    if (
        not isinstance(expected_ids, list)
        or len(expected_ids) != page.get("revision_count")
        or any(not isinstance(revision_id, int) or revision_id <= 0 for revision_id in expected_ids)
        or len(set(expected_ids)) != len(expected_ids)
    ):
        raise AssertionError("seed state omitted the complete independent core revision ID list")
    if (
        any(not isinstance(revision_id, int) or revision_id <= 0 for revision_id in actual_ids)
        or len(actual_ids) != len(expected_ids)
        or len(set(actual_ids)) != len(actual_ids)
        or set(actual_ids) != set(expected_ids)
    ):
        raise AssertionError("ready cached history revision IDs differ from the complete seeded core history")
    return cached_hash


def assert_write_guard(api_url: str, title: str, revision_id: int) -> None:
    # Check the ordinary producer schema first. These failures therefore measure
    # request protection, not a malformed fixture or a missing extension.
    ordinary = extension_result(WikiApi(api_url), title, revision_id)
    errors = validate_analyze_schema(ordinary)
    if errors:
        raise AssertionError("ordinary fixture failed the production response schema before security checks: " + "; ".join(errors))
    if ordinary["snapshot"].get("revision_id") != revision_id:
        raise AssertionError("ordinary fixture did not resolve to its expected snapshot")

    anonymous = WikiApi(api_url)
    anonymous_token = anonymous.token("csrf")
    try:
        response = anonymous.call({
            "action": "palimpsestblame", "op": "build", "title": title,
            "revision": revision_id, "token": anonymous_token,
        })
    except MediaWikiApiError as exc:
        if exc.code != "mustpostparams":
            raise AssertionError("valid-token GET build request did not fail at the POST-only parameter guard") from None
    else:
        raise AssertionError("valid-token GET build request was not rejected with mustpostparams")

    try:
        anonymous.call({
            "action": "palimpsestblame", "op": "build", "title": title,
            "revision": revision_id, "token": "invalid-token",
        }, post=True)
    except MediaWikiApiError as exc:
        if exc.code != "badtoken":
            raise AssertionError("invalid-token POST build request failed for an unrelated reason") from None
    else:
        raise AssertionError("invalid-token POST build request was accepted")

    # Status is non-mutating, but an unknown ID must never reveal job payload or
    # source text. The API may return a permission error or explicit not-found.
    try:
        response = anonymous.call({
            "action": "palimpsestblame", "op": "status", "title": title,
            "revision": revision_id, "jobid": "not-a-real-job-id",
        })
    except MediaWikiApiError as exc:
        if exc.code not in {"permissiondenied", "nosuchjob"}:
            raise AssertionError("unknown job status failed for an unrelated reason") from exc
    else:
        result = response.get("palimpsestblame", {})
        job = result.get("job", {})
        if result.get("status") != "unavailable" or result.get("reason") not in {
            "job-does-not-match-page-and-pinned-revision", "permission_denied",
        }:
            raise AssertionError("unknown job ID was not rejected explicitly")
        if any(key in job for key in ("source_text", "html", "revisions", "content")):
            raise AssertionError("job status leaked article content or revision metadata")


def verify_language(api_url: str, language_state: dict, auth: dict) -> dict:
    page = language_state.get("job_resume")
    if not page:
        raise ValueError("state file has no 205-revision job fixture; re-seed with --include-job-history")
    if page["revision_count"] <= 200 or len(page["revision_ids"]) != page["revision_count"]:
        raise AssertionError("job fixture did not exceed the frozen 200-revision synchronous limit")
    api = WikiApi(api_url)
    api.login(auth["username"], auth["password"])

    ordinary_page = language_state["pages"]["cross_contributor_deletion"]
    ordinary_revision = ordinary_page["revisions"][-1]["revision_id"]
    ordinary = extension_result(WikiApi(api_url), ordinary_page["title"], ordinary_revision)
    errors = validate_analyze_schema(ordinary)
    if errors:
        raise AssertionError("ordinary fixture schema invalid before job checks: " + "; ".join(errors))
    if ordinary["snapshot"].get("revision_id") != ordinary_revision:
        raise AssertionError("ordinary fixture did not preserve its expected snapshot before job checks")

    # Pin preparation to the original core-API revision captured during seeding.
    # The page's mutable latest may already be newer on a rerun; that must not
    # redirect this checkpoint to a different history.
    target_revision = page["revision_ids"][-1]
    prepared_response = api.call({
        "action": "palimpsestblame", "op": "analyze", "title": page["title"],
        "revision": target_revision,
    })
    prepared = action_result(prepared_response)
    if prepared.get("revision_id") != target_revision:
        raise AssertionError("analyze response changed the original pinned seed revision")
    if prepared.get("status") == "ready":
        # A previous run may already have completed this exact pinned target.
        # Treat it as durable evidence after checking the full cached payload.
        assert_ready_cached_history(prepared, page, target_revision)
    else:
        if prepared.get("buildable") is not True:
            raise AssertionError(f"205-revision fixture should advertise buildable=true; got {prepared.get('buildable')!r}")
        if prepared.get("status") != "unavailable" or not str(prepared.get("reason", "")).startswith("synchronous-history-limit-exceeded;"):
            raise AssertionError("buildable analyze response did not identify the synchronous history limit")

    # Advance latest after preparation, even on reruns. All operations below
    # remain pinned to the immutable 205-revision seed target.
    latest_text = f"job fixture latest edit after pinned target {target_revision} probe {time.time_ns()}"
    latest_revision = api.edit(
        page["title"],
        latest_text,
        f"[synthetic Blame latest-after-prepare {target_revision}]",
    )
    if latest_revision <= target_revision:
        raise AssertionError("latest-edit control did not create a revision newer than the pinned seed target")

    token = api.token("csrf")
    build_fields = {
        "action": "palimpsestblame", "op": "build", "title": page["title"],
        "revision": target_revision, "token": token,
    }
    first_response = api.call(build_fields, post=True)
    first_result = action_result(first_response)
    first_job = job_value(first_result)
    if first_result.get("revision_id") != target_revision:
        raise AssertionError("build response changed the target revision resolved by analyze")
    if first_job["status"] not in {"pending", "ready"}:
        raise AssertionError(f"205-revision build did not expose resumable or completed work: {first_job['status']}")
    if first_job.get("total") is not None and first_job["total"] < page["revision_count"]:
        raise AssertionError("build job total is below the 205-revision fixture history")
    if len(json.dumps(first_response, ensure_ascii=False).encode("utf-8")) > 2 * 1024 * 1024:
        raise AssertionError("build response exceeded the frozen 2 MiB response budget")

    job_id = str(first_job["id"])
    # A fresh client call represents a lost worker/request continuation. The API
    # must identify the same durable checkpoint instead of queuing duplicate work.
    resumed_response = api.call(build_fields, post=True)
    resumed_job = job_value(action_result(resumed_response))
    if action_result(resumed_response).get("revision_id") != target_revision:
        raise AssertionError("repeated build response lost the pinned target revision")
    if str(resumed_job["id"]) != job_id:
        raise AssertionError("repeated build created a duplicate job instead of resuming the durable checkpoint")
    if resumed_job["processed"] < first_job["processed"]:
        raise AssertionError("resumed job progress moved backwards")

    deadline = time.monotonic() + 120
    previous = resumed_job["processed"]
    latest_job = resumed_job
    while latest_job["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(1)
        status_response = api.call({
            "action": "palimpsestblame", "op": "status", "title": page["title"],
            "revision": target_revision, "jobid": job_id,
        })
        status_result = action_result(status_response)
        if status_result.get("revision_id") != target_revision:
            raise AssertionError("status response lost the pinned target revision")
        latest_job = job_value(status_result)
        if str(latest_job["id"]) != job_id or latest_job["processed"] < previous:
            raise AssertionError("job identity or checkpoint progress changed while polling")
        previous = latest_job["processed"]
        if len(json.dumps(status_response, ensure_ascii=False).encode("utf-8")) > 2 * 1024 * 1024:
            raise AssertionError("job status exceeded the frozen 2 MiB response budget")
    if latest_job["status"] != "ready":
        raise AssertionError(f"bounded job did not finish ready within 120 seconds: {latest_job['status']}")
    if latest_job.get("total") is not None and latest_job["processed"] < latest_job["total"]:
        raise AssertionError("job reported ready before all declared work was processed")

    ready_result = extension_result(api, page["title"], target_revision)
    source_hash = assert_ready_cached_history(ready_result, page, target_revision)

    assert_write_guard(api_url, page["title"], target_revision)
    return {
        "job_id": job_id,
        "revision_id": target_revision,
        "initial_status": first_job["status"],
        "processed": latest_job["processed"],
        "total": latest_job.get("total"),
        "source_text_sha256": source_hash,
        "revision_ids_verified": len(page["revision_ids"]),
    }


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
            raise ValueError("state file is not a feature-runtime synthetic fixture")
        if auth.get("scope") != "synthetic_test_accounts_only" or auth.get("project") != DOCKER_PROJECT or auth.get("run_id") != state.get("run_id"):
            raise ValueError("private test credentials do not match the synthetic fixture run")
        results = {}
        for language in LANGS:
            api_url = manifest["languages"][language]["api_url"]
            results[language] = verify_language(api_url, state["languages"][language], auth["languages"][language])
        print("PASS bounded job resume/security: " + json.dumps(results, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, MediaWikiApiError, AssertionError) as exc:
        print(f"FAIL Blame job acceptance: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
