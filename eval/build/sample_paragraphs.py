"""Sample candidate prose paragraphs (3-6 sentences) from dataset S and print them as JSON."""

import json
import random
import re
import sys
from pathlib import Path
from typing import TypedDict

import pyarrow.parquet as pq  # type: ignore[import-untyped]  # pyarrow ships no stubs

SEED = 1114
DATA_DIR = Path("data/s")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ0-9\"“])")
NON_PROSE_START = ("#", "|", "-", "*", "+", ">", "!", "[", "<", "`", "1.", "$")


class Candidate(TypedDict):
    title: str
    url: str
    paragraph: str


def is_prose(paragraph: str) -> bool:
    if paragraph.startswith(NON_PROSE_START) or "|" in paragraph or "\n" in paragraph:
        return False
    if re.search(r"[#*_\[\]{}<>]", paragraph):
        return False
    sentences = SENTENCE_SPLIT.split(paragraph)
    return 3 <= len(sentences) <= 6 and 250 <= len(paragraph) <= 1200


def sample(lang: str, count: int, rng: random.Random) -> list[Candidate]:
    table = pq.read_table(
        DATA_DIR / f"articles-{lang}.parquet", columns=["title", "url", "text"]
    )
    rows = table.to_pylist()
    rng.shuffle(rows)
    found: list[Candidate] = []
    for row in rows[:3000]:
        paragraphs = [p.strip() for p in str(row["text"]).split("\n\n")]
        prose = [p for p in paragraphs if is_prose(p)]
        if prose:
            found.append(
                Candidate(
                    title=str(row["title"]),
                    url=str(row["url"]),
                    paragraph=rng.choice(prose),
                )
            )
        if len(found) >= count:
            break
    return found


def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(
        json.dumps(
            sample(lang, count, random.Random(SEED)), ensure_ascii=False, indent=1
        )
    )


if __name__ == "__main__":
    main()
