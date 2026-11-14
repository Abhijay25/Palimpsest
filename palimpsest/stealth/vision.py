"""Pillar 3 vision layer: compare tile pixels with the DOM text of the same tile.

Stand-in for gemini-4-hydrogen: a Claude subagent reads each tile PNG through a
two-phase file exchange, like the triage and judge backends.
"""

import json
import re
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from palimpsest.stealth.models import HiddenFinding, VectorType
from palimpsest.stealth.render import RenderAudit, RenderedTile

VISION_PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "vision_v1.txt"
# An image smaller than this cannot carry a readable headline or quote.
MIN_TEXT_IMAGE_W: Final = 120
MIN_TEXT_IMAGE_H: Final = 60
MAX_VISION_TILES_PER_PAGE: Final = 3
_TAG: Final = re.compile(r"<(?=\s*/?\s*untrusted_dom_text)", re.IGNORECASE)


class VisionVerdict(BaseModel):
    item_id: str
    image_text_missing_from_dom: list[str]
    dom_text_not_visible: list[str]
    is_unindexed_claim_or_instruction: bool
    confidence: float
    explanation: str


def vision_tiles(audit: RenderAudit) -> list[RenderedTile]:
    """Tiles that overlap an image large enough to carry text, at most a few per page."""
    big = [
        r.rect
        for r in audit.image_regions
        if r.rect[2] >= MIN_TEXT_IMAGE_W and r.rect[3] >= MIN_TEXT_IMAGE_H
    ]
    chosen = [
        tile
        for tile in audit.tiles
        if any(y < tile.y_end and y + h > tile.y_start for _, y, _, h in big)
    ]
    return chosen[:MAX_VISION_TILES_PER_PAGE]


def render_vision_batch(
    items: list[tuple[str, RenderedTile]], results_path: Path
) -> str:
    instructions = VISION_PROMPT_PATH.read_text(encoding="utf-8").replace(
        "{RESULTS_PATH}", str(results_path)
    )
    blocks = [
        f'ITEM id="{item_id}"\nIMAGE: {Path(tile.png_path).resolve()}\n'
        f"<untrusted_dom_text>\n{_TAG.sub('&lt;', tile.visible_text)}\n"
        "</untrusted_dom_text>\n"
        for item_id, tile in items
    ]
    return instructions + "\n" + "\n".join(blocks)


def read_vision_verdicts(results_dir: Path) -> tuple[dict[str, VisionVerdict], int]:
    verdicts: dict[str, VisionVerdict] = {}
    invalid = 0
    for path in sorted(results_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                verdict = VisionVerdict.model_validate(json.loads(line))
            except (ValueError, ValidationError):
                invalid += 1
                continue
            verdicts[verdict.item_id] = verdict
    return verdicts, invalid


def vision_finding(verdict: VisionVerdict) -> HiddenFinding | None:
    if not verdict.is_unindexed_claim_or_instruction:
        return None
    text = " | ".join(verdict.image_text_missing_from_dom)
    return HiddenFinding(
        vector_type=VectorType.PIXEL_DOM_MISMATCH,
        raw_snippet=text[:300],
        decoded_hidden_text=text,
        char_span=(0, 0),
        classification="IMAGE_CONTAINS_UNINDEXED_TEXT",
        confidence=verdict.confidence,
        explanation=verdict.explanation,
    )
