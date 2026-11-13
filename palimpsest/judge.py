"""Stage 2: prompt rendering and the two-phase file-exchange judge backend."""

import json
from pathlib import Path
from typing import Final, Protocol

from pydantic import BaseModel, ValidationError

from palimpsest.schema import AuditOutput, Case, SourceWindow
from palimpsest.stage0 import Stage0Result

PROMPT_VERSION: Final = "stage2_v1"
PROMPTS_DIR: Final = Path(__file__).parent / "prompts"
SOURCE_UNAVAILABLE_LINE: Final = (
    "SOURCE UNAVAILABLE — judge framing from the diff only; "
    "do not flag G1/G3 for lack of a source"
)


class PreparedCase(BaseModel):
    case: Case
    stage0: Stage0Result
    window: SourceWindow | None


class _ResultLine(BaseModel):
    case_id: str


class JudgeBackend(Protocol):
    name: str


def render_case_payload(pc: PreparedCase) -> str:
    window = pc.window
    if window is None or window.status == "unavailable" or not window.text:
        discourse = SOURCE_UNAVAILABLE_LINE
    else:
        discourse = window.text
    return (
        f"=== CASE {pc.case.case_id} ===\n"
        f"OLD_TEXT:\n{pc.case.old_text}\n\n"
        f"NEW_TEXT:\n{pc.case.new_text}\n\n"
        f"CITATION_DISCOURSE_WINDOW:\n{discourse}\n\n"
        "DOMAIN_TRUST_TIER: UNKNOWN\n"
    )


class FileExchangeBackend:
    name = "file_exchange"

    def write_batches(
        self,
        prepared: list[PreparedCase],
        run_dir: Path,
        models: list[str],
        batch_size: int = 10,
    ) -> list[Path]:
        judged = [pc for pc in prepared if not pc.stage0.clean]
        instructions = (PROMPTS_DIR / "subagent_judge.txt").read_text()
        rubric = (PROMPTS_DIR / f"{PROMPT_VERSION}.txt").read_text()
        written: list[Path] = []
        for model in models:
            for index, start in enumerate(range(0, len(judged), batch_size), start=1):
                name = f"batch_{index:03d}"
                results_path = (run_dir / "results" / model / f"{name}.jsonl").resolve()
                if results_path.exists():
                    continue
                batch_path = run_dir / "batches" / model / f"{name}.md"
                batch_path.parent.mkdir(parents=True, exist_ok=True)
                payloads = "\n".join(
                    render_case_payload(pc) for pc in judged[start : start + batch_size]
                )
                batch_path.write_text(
                    instructions.replace("{RESULTS_PATH}", str(results_path))
                    + "\n"
                    + rubric
                    + "\n\n========== CASES ==========\n\n"
                    + payloads
                )
                written.append(batch_path)
        return written

    def read_results(self, run_dir: Path, model: str) -> dict[str, AuditOutput | str]:
        results: dict[str, AuditOutput | str] = {}
        for path in sorted((run_dir / "results" / model).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    case_id = _ResultLine.model_validate_json(line).case_id
                except ValidationError:
                    continue
                try:
                    raw = json.loads(line)
                    results[case_id] = AuditOutput.model_validate(raw["output"])
                except (ValueError, KeyError, ValidationError) as exc:
                    results[case_id] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return results
