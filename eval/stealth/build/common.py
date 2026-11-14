"""Shared helpers for stealth eval case builders."""

import json
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
FIELDS = [
    "case_id",
    "lang",
    "bucket",
    "provenance",
    "target_type",
    "old_text",
    "text",
    "expected_status",
    "notes",
]


def write_cases(name: str, cases: list[dict]) -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    with open(CASES_DIR / name, "w", encoding="utf-8") as fh:
        for c in cases:
            assert list(c) == FIELDS, list(c)
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(name, len(cases))


def case(
    case_id, lang, bucket, provenance, target_type, old_text, text, expected, notes
):
    return dict(
        zip(
            FIELDS,
            [
                case_id,
                lang,
                bucket,
                provenance,
                target_type,
                old_text,
                text,
                expected,
                notes,
            ],
        )
    )
