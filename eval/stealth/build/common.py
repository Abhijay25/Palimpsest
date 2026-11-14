"""Shared helpers for stealth eval case builders."""

import json
from pathlib import Path

type CaseRecord = dict[str, str | None]

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


def write_cases(name: str, cases: list[CaseRecord]) -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    with open(CASES_DIR / name, "w", encoding="utf-8") as fh:
        for c in cases:
            assert list(c) == FIELDS, list(c)
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(name, len(cases))


def case(
    case_id: str,
    lang: str,
    bucket: str,
    provenance: str,
    target_type: str,
    old_text: str | None,
    text: str,
    expected: str,
    notes: str,
) -> CaseRecord:
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
