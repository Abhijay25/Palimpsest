"""CLI entry point: python -m palimpsest prepare|ingest."""

import argparse
import asyncio
from pathlib import Path

from palimpsest.pipeline import prepare


def main() -> None:
    parser = argparse.ArgumentParser(prog="palimpsest")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Run stages 0-1 and write judge batches")
    prep.add_argument("--cases", nargs="+", type=Path, required=True)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    args = parser.parse_args()
    if args.command == "prepare":
        asyncio.run(prepare(args.cases, args.run, args.models))


if __name__ == "__main__":
    main()
