#!/usr/bin/env python3
"""Opt-in negative provenance controls on the isolated feature test runtime.

Temporarily changes only served bundle copies, restoring bytes in finally.
Original C3/C4 histories and exporter copies remain untouched. Never use on a
shared runtime. This is an integration probe, not an ordinary CI/download job.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/blame"))
from mediawiki_api import WikiApi  # noqa: E402
from verify_live import validate_analyze_schema  # noqa: E402
from runtime import resolve_docker  # noqa: E402


def checksum(bundle: dict) -> None:
    raw = json.dumps(bundle["payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    bundle["sha256"] = hashlib.sha256(raw).hexdigest()


def replace_file(path: Path, data: bytes, mode: int) -> None:
    # Readers must see a complete old or new bundle, never a truncated writer.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def wait_visible(language: str, expected: bytes | None) -> None:
    """Observe the actual mounted bytes before asserting a specific guard."""
    docker, env = resolve_docker()
    wanted = hashlib.sha256(expected).hexdigest() if expected is not None else "missing"
    code = f"$p='/etc/palimpsest/{language}.json'; clearstatcache(true,$p); echo is_file($p) ? hash_file('sha256',$p) : 'missing';"
    for _ in range(20):
        observation = subprocess.run([docker, "exec", "-u", "www-data", f"palimpsest-blame-wiki-{language}-1", "php", "-r", code], env=env, capture_output=True, text=True, check=True, timeout=10)
        if observation.stdout == wanted:
            return
        time.sleep(0.1)
    raise AssertionError("served fixture bytes did not become visible in the isolated container")


def result(api: WikiApi, title: str, revision: int) -> dict:
    return api.call({"action": "palimpsestblame", "title": title, "revision": revision})["palimpsestblame"]


def require_ready(data: dict) -> None:
    errors = validate_analyze_schema(data)
    if errors:
        raise AssertionError("ordinary schema failed before negative control: " + "; ".join(errors))


def require_unavailable(data: dict, reason: str) -> None:
    if data.get("status") != "unavailable" or data.get("reason") != reason:
        raise AssertionError(f"expected unavailable/{reason}, got {data.get('status')}/{data.get('reason')}")
    if any(key in data for key in ("source_text", "html", "spans", "revisions", "events")):
        raise AssertionError("invalid provenance response exposed attribution/content")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--local-edit-auth", type=Path, help="optional private synthetic-account file for one reversible edit on the English sample")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    manifest = json.loads((data_root / "runtime.json").read_text())
    if args.confirm_project != "palimpsest-blame" or manifest.get("project") != args.confirm_project:
        parser.error("this probe only supports the explicitly confirmed isolated palimpsest-blame runtime")
    for language, port in (("fi", 48081), ("sv", 48082), ("en", 48083)):
        if manifest["languages"][language]["api_url"] != f"http://127.0.0.1:{port}/api.php":
            parser.error("control endpoints must be the exact isolated loopback APIs")
    report = {}
    for lang in ("fi", "sv", "en"):
        print(f"Checking {lang} provenance controls", file=sys.stderr, flush=True)
        path = data_root / "config" / lang / f"{lang}.json"
        original = path.read_bytes()
        mode = path.stat().st_mode & 0o777
        bundle = json.loads(original)
        page = bundle["payload"]["pages"][0]
        target = next(row["local_revision_id"] for row in page["revisions"] if row["source_revision_id"] == page["source_anchor_revision_id"])
        api = WikiApi(manifest["languages"][lang]["api_url"])
        require_ready(result(api, page["title"], target))
        cases = []
        try:
            bad = copy.deepcopy(bundle)
            bad["sha256"] = "0" * 64
            replace_file(path, json.dumps(bad, ensure_ascii=False).encode(), mode)
            wait_visible(lang, path.read_bytes())
            require_unavailable(result(api, page["title"], target), "provenance-bundle-checksum-mismatch")
            cases.append("payload checksum mismatch")

            bad = copy.deepcopy(bundle)
            bad["payload"]["pages"] = [row for row in bad["payload"]["pages"] if row["local_page_id"] != page["local_page_id"]]
            checksum(bad)
            replace_file(path, json.dumps(bad, ensure_ascii=False).encode(), mode)
            wait_visible(lang, path.read_bytes())
            require_unavailable(result(api, page["title"], target), "provenance-page-record-missing")
            cases.append("missing page in otherwise valid bundle")

            bad = copy.deepcopy(bundle)
            bad["payload"]["pages"][0]["revisions"][0]["sha256"] = "0" * 64
            checksum(bad)
            replace_file(path, json.dumps(bad, ensure_ascii=False).encode(), mode)
            wait_visible(lang, path.read_bytes())
            require_unavailable(result(api, page["title"], target), "provenance-record-does-not-match-local-revision")
            cases.append("forged revision inside checksummed bundle")

            bad = copy.deepcopy(bundle)
            bad["payload"]["pages"][0]["history_complete"] = False
            checksum(bad)
            replace_file(path, json.dumps(bad, ensure_ascii=False).encode(), mode)
            wait_visible(lang, path.read_bytes())
            require_unavailable(result(api, page["title"], target), "imported-history-incomplete")
            cases.append("explicitly incomplete imported history")

            path.unlink()
            wait_visible(lang, None)
            require_unavailable(result(api, page["title"], target), "provenance-bundle-missing-or-too-large")
            cases.append("missing served bundle")
        finally:
            replace_file(path, original, mode)
            wait_visible(lang, original)
        require_ready(result(api, page["title"], target))
        report[lang] = {"negative_controls": cases, "restored": path.read_bytes() == original}

    if args.local_edit_auth:
        auth = json.loads(args.local_edit_auth.read_text())
        if auth.get("project") != args.confirm_project or auth.get("scope") != "synthetic_test_accounts_only":
            raise ValueError("credentials are not from this isolated synthetic test run")
        api = WikiApi(manifest["languages"]["en"]["api_url"])
        api.login(auth["languages"]["en"]["username"], auth["languages"]["en"]["password"])
        bundle = json.loads((data_root / "config/en/en.json").read_text())
        page = bundle["payload"]["pages"][0]
        before = result(api, page["title"], 0)
        require_ready(before)
        original_text = before["source_text"]
        marker = "PalimpsestLocalVerificationMarker"
        try:
            revision = api.edit(page["title"], original_text + "\n\n" + marker, "Clearly synthetic local prototype attribution check")
            after = result(api, page["title"], 0)
            require_ready(after)
            if after["snapshot"]["revision_id"] != revision or after["snapshot"].get("source") is not None:
                raise AssertionError("latest local edit has stale or fabricated source provenance")
            start = len(after["source_text"].split(marker)[0].encode("utf-16-le")) // 2
            covering = [s for s in after["spans"] if s["start"] <= start < s["end"]]
            if not covering or any(s["revision_id"] != revision for s in covering):
                raise AssertionError("new local wording did not invalidate latest attribution")
            if after["coverage"]["source_anchor_revision_id"] != page["source_anchor_revision_id"]:
                raise AssertionError("local edit changed the retained original source anchor")
            report["local_edit"] = {"revision_id": revision, "source": None, "source_anchor_preserved": True}
        finally:
            api.edit(page["title"], original_text, "Restore article wording after local prototype verification")
        require_ready(result(api, page["title"], 0))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
