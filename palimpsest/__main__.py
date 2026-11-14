"""CLI entry point: python -m palimpsest prepare|ingest|diagnose|audit-page."""

import argparse
import asyncio
import sys
from pathlib import Path

from palimpsest.judge import PROMPT_VERSION
from palimpsest.pipeline import ingest, prepare
from palimpsest.schema import load_cases
from palimpsest.sources import SourceFetcher, load_exa_api_key
from palimpsest.value_check import check_case


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "diagnose":
        from palimpsest.diagnose import main as diagnose_main

        raise SystemExit(diagnose_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "audit-page":
        from palimpsest.page_audit import main as page_audit_main

        raise SystemExit(page_audit_main(sys.argv[2:]))
    parser = argparse.ArgumentParser(prog="palimpsest")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Run stages 0-1 and write judge batches")
    prep.add_argument("--cases", nargs="+", type=Path, required=True)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    prep.add_argument("--prompt", default=PROMPT_VERSION, help="prompts/<name>.txt")
    prep.add_argument("--batch-size", type=int, default=10)
    prep.add_argument(
        "--source-mode",
        choices=["highlights", "lexical"],
        default="highlights",
        help="citation context selection for eval comparisons",
    )
    prep.add_argument(
        "--followup",
        action="store_true",
        help="record follow-up context as enabled for this eval run",
    )
    prep.add_argument(
        "--context-mode",
        choices=["never", "rule", "always"],
        default="rule",
        help="when bounded whole-source Exa highlights may supplement an excerpt",
    )
    prep.add_argument(
        "--value-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="record deterministic value-check evidence (default: enabled)",
    )
    prep.add_argument(
        "--reviewer",
        action="store_true",
        help="run one Argon second opinion per flagged or borderline edit (Gemini only)",
    )
    prep.add_argument(
        "--backend",
        choices=["file", "gemini"],
        default="file",
        help="file: Claude-subagent exchange; gemini: direct API (needs GEMINI_API_KEY)",
    )
    ing = sub.add_parser("ingest", help="Read judge results, score, render report.html")
    ing.add_argument("--run", type=Path, required=True)
    ing.add_argument("--compare", type=Path, default=None)
    sub.add_parser("diagnose", help="Run one edit through audit-diff in-process")
    sub.add_parser("audit-page", help="Audit the current version of a Wikipedia page")
    values = sub.add_parser("value-check", help="Run deterministic value checks only")
    values.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        asyncio.run(
            prepare(
                args.cases,
                args.run,
                args.models,
                args.prompt,
                args.batch_size,
                args.backend,
                source_mode=args.source_mode,
                followup=args.followup,
                context_mode=args.context_mode,
                value_check=args.value_check,
                reviewer=args.reviewer,
            )
        )
    elif args.command == "ingest":
        ingest(args.run, args.compare)
    elif args.command == "value-check":

        async def run_value_check() -> None:
            fetcher = SourceFetcher(load_exa_api_key(), Path("cache/exa")).for_request(
                60
            )
            reports = await asyncio.gather(
                *(check_case(case, fetcher) for case in load_cases(args.cases))
            )
            counts = {
                key: 0 for key in ("SUPPORTS_OLD", "SUPPORTS_NEW", "BOTH", "NEITHER")
            }
            for report in reports:
                for check in report.checks:
                    counts[check.outcome] += 1
            print(" ".join(f"{key}={value}" for key, value in counts.items()))

        asyncio.run(run_value_check())


if __name__ == "__main__":
    main()
