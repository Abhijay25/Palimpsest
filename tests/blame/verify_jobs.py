"""Exercise bounded build/status resume and write-API protection on synthetic pages."""

from __future__ import annotations

import argparse
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
    try:
        response = anonymous.call({
            "action": "palimpsestblame", "op": "build", "title": title,
            "revision": revision_id,
        })
    except MediaWikiApiError as exc:
        if exc.code not in {"mustbeposted", "mustpost", "badtoken", "permissiondenied"}:
            raise AssertionError("GET build request failed for an unrelated reason") from exc
    else:
        result = response.get("palimpsestblame", {})
        if result.get("status") != "failed" or result.get("reason") not in {"post_required", "bad_token", "permission_denied"}:
            raise AssertionError("GET build request was not rejected by its write guard")

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
        if result.get("status") not in {"failed", "unavailable"} or result.get("reason") not in {"job_not_found", "permission_denied"}:
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

    # Preparation is a separate read operation. The target must be taken from
    # this server response, never guessed from a client-side latest lookup.
    prepared_response = api.call({
        "action": "palimpsestblame", "op": "analyze", "title": page["title"],
    })
    prepared = action_result(prepared_response)
    if prepared.get("buildable") is not True:
        raise AssertionError(f"205-revision fixture should advertise buildable=true; got {prepared.get('buildable')!r}")
    target_revision = prepared.get("revision_id")
    if not isinstance(target_revision, int) or target_revision <= 0:
        raise AssertionError("buildable analyze response omitted its positive resolved top-level revision_id")
    if target_revision != page["revision_ids"][-1]:
        raise AssertionError("analyze resolved a target other than the seeded latest revision")

    # Advance latest after preparation. All subsequent operations must stay
    # pinned to the revision returned above.
    api.edit(
        page["title"],
        "job fixture revision 205 common prefix anchor205 common suffix",
        "T4 latest edit after job preparation",
    )

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
    if first_job["status"] != "pending":
        raise AssertionError(f"205-revision build did not expose resumable pending work: {first_job['status']}")
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

    assert_write_guard(api_url, page["title"], target_revision)
    return {"job_id": job_id, "revision_id": target_revision, "processed": latest_job["processed"], "total": latest_job.get("total")}


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
