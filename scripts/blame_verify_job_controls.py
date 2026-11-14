#!/usr/bin/env python3
"""Opt-in synthetic checkpoint/restart and suppressed-cache privacy probe.

Operates only on palimpsest-blame English at 127.0.0.1:48083. The generated
admin password stays in memory. Always restarts the feature-only queue and
restores visibility. No original imported pages or other environments change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/blame"))
from mediawiki_api import WikiApi  # noqa: E402
from verify_live import validate_analyze_schema  # noqa: E402
from runtime import resolve_docker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--confirm-project", required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    manifest = json.loads((data_root / "runtime.json").read_text())
    if args.confirm_project != "palimpsest-blame" or manifest.get("project") != args.confirm_project or manifest["languages"]["en"]["api_url"] != "http://127.0.0.1:48083/api.php":
        parser.error("requires the explicitly confirmed isolated English feature runtime")
    docker, env = resolve_docker()

    def run(*arguments: str) -> None:
        completed = subprocess.run([docker, *arguments], env=env, text=True, capture_output=True, timeout=30)
        if completed.returncode:
            raise RuntimeError(f"isolated Docker control failed ({completed.returncode}): {completed.stdout[-3000:]} {completed.stderr[-3000:]}")

    api = WikiApi("http://127.0.0.1:48083/api.php")
    public = WikiApi(api.api_url)
    api.login("admin", (data_root / "secrets/en/admin-password").read_text().strip())
    title = "PalimpsestBlameSynthetic/RootControls/" + uuid.uuid4().hex[:10]
    revisions = [api.edit(title, f"Clearly synthetic privacy checkpoint stage{letter} stable wording.", "Synthetic checkpoint/privacy control") for letter in "ABCDEFGHI"]
    target = revisions[-2]  # Historical target; hiding the current revision is disallowed by core.
    params = {"action": "palimpsestblame", "title": title, "revision": target}

    def status(job_id: str) -> dict:
        return public.call({**params, "op": "status", "jobid": job_id})["palimpsestblame"]

    ordinary = public.call(params)["palimpsestblame"]
    if validate_analyze_schema(ordinary):
        raise AssertionError("ordinary schema failed before job/privacy controls")
    hidden = False
    try:
        run("stop", "palimpsest-blame-jobs-en-1")
        build = api.call({**params, "op": "build", "token": api.token("csrf")}, post=True)["palimpsestblame"]
        job_id = build["job"]["id"]
        run("exec", "palimpsest-blame-wiki-en-1", "php", "maintenance/run.php", "runJobs", "--type=palimpsestblamebuild", "--maxjobs=1", "--maxtime=10", "--memory-limit=256M")
        checkpoint = status(job_id)
        processed = checkpoint["job"]["processed"]
        if checkpoint["status"] != "pending" or not 0 < processed < 8:
            raise AssertionError(f"one bounded job did not leave a durable partial checkpoint: {checkpoint.get('status')}, {processed}")
        run("start", "palimpsest-blame-jobs-en-1")
        deadline = time.monotonic() + 60
        while True:
            cached = status(job_id)
            if cached["status"] == "ready":
                break
            if cached["status"] == "failed" or time.monotonic() >= deadline:
                raise AssertionError(f"resumed job failed: {cached.get('job', {}).get('reason')}")
            time.sleep(0.3)
        if validate_analyze_schema(cached) or cached["snapshot"]["revision_id"] != target or cached["job"]["processed"] != 8:
            raise AssertionError("resumed cached result did not preserve the exact historical target and full history")
        if public.call(params)["palimpsestblame"]["snapshot"]["revision_id"] != target:
            raise AssertionError("analyze did not reuse the ready revision-specific cache")

        deletion = {"action": "revisiondelete", "type": "revision", "ids": revisions[0], "reason": "Synthetic cached-result visibility control", "token": api.token("csrf")}
        api.call({**deletion, "hide": "content|comment|user"}, post=True)
        hidden = True
        for op in ("analyze", "status"):
            response = public.call({**params, "op": op, **({"jobid": job_id} if op == "status" else {})})["palimpsestblame"]
            if response.get("status") != "unavailable" or response.get("reason") != "cached-history-now-unavailable":
                raise AssertionError(f"cached {op} did not reject newly hidden history: {response.get('status')}/{response.get('reason')}")
            if any(key in response for key in ("source_text", "html", "spans", "revisions", "events")):
                raise AssertionError("cached result leaked newly hidden content or metadata")
    finally:
        try:
            if hidden:
                api.call({**deletion, "show": "content|comment|user", "token": api.token("csrf")}, post=True)
        finally:
            run("start", "palimpsest-blame-jobs-en-1")
    recovered = status(job_id)
    if validate_analyze_schema(recovered):
        raise AssertionError("cached result did not recover after visibility restoration")
    print(json.dumps({"title": title, "target_revision": target, "job_id": job_id, "checkpoint_processed": processed, "resumed_processed": recovered["job"]["processed"], "suppressed_cache_read_blocked": True, "visibility_restored": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
