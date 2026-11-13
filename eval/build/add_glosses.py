"""Merge hand-written English glosses (fi_glosses.json) into the Finnish case files."""

import json
from pathlib import Path

from palimpsest.schema import dump_jsonl, load_cases

CASES_DIR = Path("eval/cases")
GLOSSES_PATH = Path("eval/build/fi_glosses.json")
FILES = ("fi_reverts.jsonl", "fi_controls.jsonl")


def load_glosses() -> dict[str, str]:
    raw: object = json.loads(GLOSSES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{GLOSSES_PATH} must contain a JSON object")
    return {str(key): str(value) for key, value in raw.items()}


def main() -> None:
    glosses = load_glosses()
    for name in FILES:
        cases = load_cases(CASES_DIR / name)
        missing = [c.case_id for c in cases if c.case_id not in glosses]
        if missing:
            raise ValueError(f"missing glosses for {missing}")
        for case in cases:
            case.en_gloss = glosses[case.case_id]
        dump_jsonl(CASES_DIR / name, cases)
        print(f"{name}: glossed {len(cases)} cases")


if __name__ == "__main__":
    main()
