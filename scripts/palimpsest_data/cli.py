from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .container import run_parquet_worker
from .coverage import build_coverage, write_coverage, exit_for_report
from .dataset import fetch_assets
from .history import GIB, acquire_corpus, probe_anchor_sample
from .importer import import_corpus
from .io import DataError, atomic_json
from .manifests import load_corpus
from .support import acquire_support_corpus


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ports_arg(value: str) -> dict[str, int]:
    try:
        parts = [int(x) for x in value.split(",")]
    except ValueError as e:
        raise argparse.ArgumentTypeError("ports must be FI,SV,EN integers") from e
    if len(parts) != 3 or len(set(parts)) != 3 or any(x < 1 or x > 65535 for x in parts):
        raise argparse.ArgumentTypeError("ports must be three unique TCP ports between 1 and 65535")
    return dict(zip(("fi", "sv", "en"), parts))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Palimpsest corpus and source-history pipeline")
    p.add_argument("--project", default="palimpsest")
    p.add_argument("--data-root", type=Path, default=repo_root() / ".local/wiki")
    p.add_argument("--ports", type=ports_arg, default=ports_arg("8081,8082,8083"))
    commands = p.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("dataset")
    ds = dataset.add_subparsers(dest="dataset_command", required=True)
    fetch = ds.add_parser("fetch")
    fetch.add_argument("--lock", type=Path, default=repo_root() / "datasets.lock.json")
    fetch.add_argument("--skip-membership", action="store_true", help="fetch locked bytes but do not parse membership")
    history = commands.add_parser("history")
    hs = history.add_subparsers(dest="history_command", required=True)
    acquire = hs.add_parser("acquire")
    acquire.add_argument("--sample-manifest", type=Path)
    acquire.add_argument("--all-pages", action="store_true", help="explicitly opt into full S history acquisition")
    acquire.add_argument("--interval", type=float, default=1.0)
    acquire.add_argument("--min-free-gib", type=float, help="free disk floor checked before acquisition and each committed batch (default: 2 GiB sample, 50 GiB full)")
    probe = hs.add_parser("probe-anchors", help="verify real sample anchor IDs and immediate public history only")
    probe.add_argument("--sample-manifest", type=Path)
    probe.add_argument("--interval", type=float, default=1.0)
    imp = commands.add_parser("data")
    ids = imp.add_subparsers(dest="data_command", required=True)
    do_import = ids.add_parser("import")
    do_import.add_argument("--sample-manifest", type=Path)
    do_import.add_argument("--all-pages", action="store_true")
    do_import.add_argument("--container-data-root", default="/data")
    do_import.add_argument("--dry-run", action="store_true")
    support = ids.add_parser("support", help="acquire sample rendering dependencies at their anchor timestamps")
    support.add_argument("--sample-manifest", type=Path)
    support.add_argument("--anchor-spike", type=Path)
    support.add_argument("--interval", type=float, default=1.0)
    support.add_argument("--max-requests", type=int, default=50, help="maximum source API requests for this support run; progress checkpoints allow a later larger-budget resume")
    support.add_argument("--max-pages-per-root", type=int, default=1000)
    verify = commands.add_parser("verify")
    verify.add_argument("--scope", choices=("sample", "full"), required=True)
    verify.add_argument("--sample-manifest", type=Path)
    return p


def _manifest_for(args, scope: str | None = None) -> Path:
    if getattr(args, "sample_manifest", None):
        return args.sample_manifest.resolve()
    if scope is None and getattr(args, "all_pages", False):
        scope = "full"
    name = "full-corpus.json" if scope == "full" else "sample-corpus.json"
    return args.data_root / "dataset" / "manifests" / name


def _run(args: argparse.Namespace) -> int:
    root = repo_root()
    data_root = args.data_root.expanduser().resolve()
    if not args.project or len(args.project) > 63 or not all(c.isalnum() or c in "-_." for c in args.project):
        raise DataError("project must be a non-empty Docker-compatible name (letters, digits, dash, underscore, dot)")
    args.data_root = data_root
    if args.command == "dataset" and args.dataset_command == "fetch":
        raw = data_root / "dataset" / "raw"
        result = fetch_assets(args.lock.resolve(), raw)
        if not args.skip_membership:
            parsed = run_parquet_worker(root, raw, data_root / "dataset" / "manifests")
            result["membership"] = json.loads((data_root / "dataset" / "manifests" / "full-corpus.json").read_text(encoding="utf-8"))["expected_counts"]
            result["sample_manifest"] = str(data_root / "dataset" / "manifests" / "sample-corpus.json")
            result["tooling_image"] = parsed["image"]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "history" and args.history_command == "acquire":
        corpus_path = _manifest_for(args)
        corpus = load_corpus(corpus_path)
        if corpus["scope"] == "full" and not args.all_pages:
            raise DataError("full history acquisition requires --all-pages")
        if corpus["scope"] == "sample" and args.all_pages:
            raise DataError("--all-pages cannot be combined with a sample manifest")
        min_free_gib = args.min_free_gib if args.min_free_gib is not None else (50.0 if corpus["scope"] == "full" else 2.0)
        result = acquire_corpus(corpus_path, data_root / "history", allow_full=args.all_pages, interval=args.interval,
                                progress_path=data_root / "history" / f"acquisition-{corpus['scope']}.json",
                                min_free_bytes=int(min_free_gib * GIB))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if all(a.get("exhausted") and not a.get("error") for a in result["articles"]) else 1
    if args.command == "history" and args.history_command == "probe-anchors":
        corpus_path = _manifest_for(args)
        result = probe_anchor_sample(corpus_path, interval=args.interval)
        path = data_root / "reports" / "anchor-spike.json"
        atomic_json(path, result)
        print(json.dumps({"report": str(path), "complete": result["complete"], "by_language": result["by_language"], "pages": [
            {"language": p["language"], "source_page_id": p["source_page_id"], "anchor_revision_id": p["anchor_revision_id"],
             "title": p["title"], "anchor_matches": p.get("anchor_matches", False), "anchor_timestamp_matches": p.get("anchor_timestamp_matches", False),
             "public_revisions_returned": p.get("public_revisions_returned", 0), "has_public_predecessor": p.get("has_public_predecessor", False), "error": p.get("error")}
            for p in result["pages"]]}, indent=2, sort_keys=True))
        return 0 if result["complete"] else 1
    if args.command == "data" and args.data_command == "import":
        corpus_path = _manifest_for(args)
        corpus = load_corpus(corpus_path)
        if corpus["scope"] == "full" and not args.all_pages:
            raise DataError("full import requires --all-pages")
        if corpus["scope"] == "sample" and args.all_pages:
            raise DataError("--all-pages cannot be combined with a sample manifest")
        result = import_corpus(corpus_path, data_root / "history", data_root / "imports", data_root / "runtime.json",
                               root / "scripts/runtime.py", container_data_root=args.container_data_root, dry_run=args.dry_run,
                               expected_project=args.project, expected_data_root=str(data_root))
        atomic_json(data_root / "imports" / f"import-{corpus['scope']}.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("support_complete") and all(p.get("status") in {"reconciled", "already-reconciled", "prepared"} for p in result["pages"]) else 1
    if args.command == "data" and args.data_command == "support":
        corpus_path = _manifest_for(args)
        spike_path = args.anchor_spike.resolve() if args.anchor_spike else data_root / "reports" / "anchor-spike.json"
        if args.max_requests < 0 or args.max_pages_per_root < 1:
            raise DataError("support request/page budgets must be nonnegative and positive respectively")
        result = acquire_support_corpus(corpus_path, spike_path, data_root / "support", interval=args.interval,
                                       max_requests=args.max_requests, max_pages=args.max_pages_per_root)
        atomic_json(data_root / "reports" / "support-sample.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["complete"] else 1
    if args.command == "verify":
        corpus_path = _manifest_for(args, args.scope)
        corpus = load_corpus(corpus_path)
        if corpus["scope"] != args.scope:
            raise DataError(f"manifest scope {corpus['scope']} does not match requested --scope {args.scope}")
        runtime_path = data_root / "runtime.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else None
        code = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False).stdout.strip() or "unknown"
        report = build_coverage(corpus, data_root, project=args.project, runtime_manifest=runtime, code_revision=code)
        path = data_root / "coverage.json"
        write_coverage(path, report)
        print(json.dumps({"report": str(path), **report}, indent=2, sort_keys=True))
        return exit_for_report(report)
    raise DataError("unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return _run(args)
    except DataError as e:
        print(f"data: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
