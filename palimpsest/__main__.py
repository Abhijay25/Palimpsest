"""CLI entry point: python -m palimpsest prepare|ingest|diagnose."""

import argparse
import asyncio
import sys
from pathlib import Path

from palimpsest.judge import PROMPT_VERSION
from palimpsest.pipeline import ingest, prepare


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "diagnose":
        from palimpsest.diagnose import main as diagnose_main

        raise SystemExit(diagnose_main(sys.argv[2:]))
    parser = argparse.ArgumentParser(prog="palimpsest")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Run stages 0-1 and write judge batches")
    prep.add_argument("--cases", nargs="+", type=Path, required=True)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    prep.add_argument("--prompt", default=PROMPT_VERSION, help="prompts/<name>.txt")
    prep.add_argument("--batch-size", type=int, default=10)
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
            )
        )
    elif args.command == "ingest":
        ingest(args.run, args.compare)


if __name__ == "__main__":
    main()
