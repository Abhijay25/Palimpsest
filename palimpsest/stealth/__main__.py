import argparse
from pathlib import Path

from palimpsest.stealth.scanner import TargetType, scan


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m palimpsest.stealth")
    parser.add_argument("file", type=Path)
    parser.add_argument("--target-type", default="WIKIPEDIA_DIFF")
    parser.add_argument("--old-file", type=Path, default=None)
    args = parser.parse_args()
    if args.target_type not in ("WIKIPEDIA_DIFF", "EXTERNAL_REF_PAGE"):
        parser.error("--target-type must be WIKIPEDIA_DIFF or EXTERNAL_REF_PAGE")
    target: TargetType = args.target_type
    old = args.old_file.read_text(encoding="utf-8") if args.old_file else None
    result = scan(args.file.read_text(encoding="utf-8"), target, old)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
