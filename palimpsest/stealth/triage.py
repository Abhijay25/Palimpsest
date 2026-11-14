"""Pillar 2: differential triage of hidden-channel text (two-phase file exchange)."""

import json
import re
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from palimpsest.stealth.models import (
    HiddenFinding,
    ScanResult,
    StealthStatus,
    VectorType,
)

TRIAGE_PROMPT_PATH: Final = Path(__file__).parent / "prompts" / "triage_v1.txt"

# Ascending severity: later entries win.
_SEVERITY: Final = [
    StealthStatus.CLEAN,
    StealthStatus.BENIGN_NOTES_ONLY,
    StealthStatus.HOMOGLYPH_SPOOFING,
    StealthStatus.CSS_CLOAKING_DETECTED,
    StealthStatus.CRITICAL_AI_POISONING,
]

_PROVISIONAL_STATUS: Final[dict[str, StealthStatus]] = {
    "FLAG_STEALTH_PROMPT_INJECTION": StealthStatus.CRITICAL_AI_POISONING,
    "FLAG_CSS_CLOAKING": StealthStatus.CSS_CLOAKING_DETECTED,
    "FLAG_HOMOGLYPH_SPOOFING": StealthStatus.HOMOGLYPH_SPOOFING,
    "FLAG_BIDI_OVERRIDE": StealthStatus.HOMOGLYPH_SPOOFING,
    "BENIGN_EDITOR_NOTE_PROVISIONAL": StealthStatus.BENIGN_NOTES_ONLY,
    "NEEDS_TRIAGE": StealthStatus.BENIGN_NOTES_ONLY,
}

_OPENING_OR_CLOSING_TAG: Final = re.compile(
    r"<(?=\s*/?\s*untrusted_hidden_channel)", re.IGNORECASE
)


class TriageVerdict(BaseModel):
    finding_id: str
    is_prompt_injection: bool
    is_narrative_or_seo_cloaking: bool
    is_benign_editor_note: bool
    confidence: float
    explanation: str


class _VerdictLine(BaseModel):
    finding_id: str


def finding_text(finding: HiddenFinding) -> str:
    return finding.decoded_hidden_text or finding.raw_snippet


def _needs_triage(finding: HiddenFinding) -> bool:
    if (
        finding.vector_type == VectorType.INVISIBLE_CONTROL_CHARS
        and not finding.decoded_hidden_text
    ):
        return False
    return bool(finding_text(finding))


def triage_items(result: ScanResult) -> list[tuple[str, HiddenFinding]]:
    """Findings needing triage, paired with their stable id (scan_id:index)."""
    return [
        (f"{result.scan_id}:{index}", finding)
        for index, finding in enumerate(result.hidden_findings)
        if _needs_triage(finding)
    ]


def hidden_delta(result: ScanResult) -> list[HiddenFinding]:
    return [finding for _, finding in triage_items(result)]


def render_triage_batch(
    items: list[tuple[str, HiddenFinding]], results_path: Path
) -> str:
    instructions = TRIAGE_PROMPT_PATH.read_text(encoding="utf-8").replace(
        "{RESULTS_PATH}", str(results_path)
    )
    blocks: list[str] = []
    for finding_id, finding in items:
        safe_id = finding_id.replace('"', "&quot;")
        payload = _OPENING_OR_CLOSING_TAG.sub("&lt;", finding_text(finding))
        blocks.append(
            f'<untrusted_hidden_channel id="{safe_id}">\n{payload}\n'
            "</untrusted_hidden_channel>\n"
        )
    return instructions + "\n" + "\n".join(blocks)


def read_verdicts(run_dir: Path, model: str) -> tuple[dict[str, TriageVerdict], int]:
    """Parse results/<model>/*.jsonl; returns (verdicts, invalid_line_count)."""
    verdicts: dict[str, TriageVerdict] = {}
    invalid = 0
    for path in sorted((run_dir / "results" / model).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                verdict = TriageVerdict.model_validate(json.loads(line))
            except (ValueError, ValidationError):
                invalid += 1
                continue
            verdicts[verdict.finding_id] = verdict
    return verdicts, invalid


def _max_status(statuses: list[StealthStatus]) -> StealthStatus:
    return max(statuses, key=_SEVERITY.index, default=StealthStatus.CLEAN)


def _final_for_triaged(
    finding: HiddenFinding, verdict: TriageVerdict
) -> tuple[StealthStatus, str]:
    if verdict.is_prompt_injection:
        return (
            StealthStatus.CRITICAL_AI_POISONING,
            "FLAG_STEALTH_PROMPT_INJECTION",
        )
    if verdict.is_narrative_or_seo_cloaking:
        return (
            StealthStatus.CSS_CLOAKING_DETECTED,
            "FLAG_STEALTH_NARRATIVE_CLOAKING",
        )
    if finding.vector_type == VectorType.HOMOGLYPH_MIXED_SCRIPT:
        return StealthStatus.HOMOGLYPH_SPOOFING, finding.classification
    if verdict.is_benign_editor_note:
        return StealthStatus.BENIGN_NOTES_ONLY, "BENIGN_EDITOR_NOTE"
    return StealthStatus.BENIGN_NOTES_ONLY, "TRIAGE_NO_FLAG"


def apply_triage(result: ScanResult, verdicts: dict[str, TriageVerdict]) -> ScanResult:
    triaged = {fid: index for index, (fid, _) in enumerate(triage_items(result))}
    index_to_id = {int(fid.rsplit(":", 1)[1]): fid for fid in triaged}
    findings: list[HiddenFinding] = []
    statuses: list[StealthStatus] = []
    for index, finding in enumerate(result.hidden_findings):
        fid = index_to_id.get(index)
        provisional = _PROVISIONAL_STATUS.get(finding.classification)
        if finding.vector_type == VectorType.UNICODE_TAG_SMUGGLING:
            statuses.append(StealthStatus.CRITICAL_AI_POISONING)
            findings.append(finding)
        elif fid is None:
            if provisional is not None:
                statuses.append(provisional)
            findings.append(finding)
        elif fid in verdicts:
            verdict = verdicts[fid]
            status, classification = _final_for_triaged(finding, verdict)
            statuses.append(status)
            findings.append(
                finding.model_copy(
                    update={
                        "classification": classification,
                        "confidence": verdict.confidence,
                        "explanation": verdict.explanation,
                    }
                )
            )
        else:
            if provisional is not None:
                statuses.append(provisional)
            findings.append(
                finding.model_copy(update={"classification": "TRIAGE_MISSING"})
            )
    return result.model_copy(
        update={"stealth_status": _max_status(statuses), "hidden_findings": findings}
    )
