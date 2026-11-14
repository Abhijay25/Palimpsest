"""Stealth evaluation harness: prepare triage batches, ingest verdicts, score."""

import argparse
import html
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from palimpsest.stealth.models import ScanResult, StealthStatus
from palimpsest.stealth.scanner import scan
from palimpsest.stealth.triage import (
    TriageVerdict,
    apply_triage,
    read_verdicts,
    render_triage_batch,
    triage_items,
)

_FLAGGED = frozenset(
    {
        StealthStatus.CRITICAL_AI_POISONING,
        StealthStatus.CSS_CLOAKING_DETECTED,
        StealthStatus.HOMOGLYPH_SPOOFING,
    }
)
_QUIET = frozenset({StealthStatus.CLEAN, StealthStatus.BENIGN_NOTES_ONLY})


class StealthCase(BaseModel):
    case_id: str
    lang: str
    bucket: str
    provenance: str
    target_type: Literal["WIKIPEDIA_DIFF", "EXTERNAL_REF_PAGE"]
    old_text: str | None
    text: str
    expected_status: StealthStatus
    notes: str


class PreparedStealth(BaseModel):
    case: StealthCase
    pillar1: ScanResult


class Manifest(BaseModel):
    models: list[str]


class CaseOutcome(BaseModel):
    case_id: str
    model: str
    expected_status: StealthStatus
    pillar1_status: StealthStatus
    final_status: StealthStatus
    final: ScanResult


class ModelMetrics(BaseModel):
    n: int
    accuracy: float
    false_alarm_rate: float
    miss_rate: float
    pillar1_accuracy: float
    p50_latency_ms: float
    p95_latency_ms: float
    invalid_verdict_lines: int


def make_visible(text: str) -> str:
    out: list[str] = []
    for char in text:
        code = ord(char)
        is_tag = 0xE0000 <= code <= 0xE007F
        category = unicodedata.category(char)
        if is_tag or (category in ("Cf", "Cc") and char not in "\n\t"):
            out.append(f"⟦U+{code:04X}⟧")
        else:
            out.append(char)
    return "".join(out)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct * (len(ordered) - 1)))]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def load_stealth_cases(paths: list[Path]) -> list[StealthCase]:
    cases: list[StealthCase] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(StealthCase.model_validate_json(line))
    return cases


def prepare(
    case_files: list[Path], run_dir: Path, models: list[str], batch_size: int = 40
) -> list[Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[PreparedStealth] = []
    for case in load_stealth_cases(case_files):
        result = scan(case.text, case.target_type, case.old_text)
        prepared.append(
            PreparedStealth(
                case=case, pillar1=result.model_copy(update={"scan_id": case.case_id})
            )
        )
    (run_dir / "prepared.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in prepared), encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        Manifest(models=models).model_dump_json(), encoding="utf-8"
    )
    items = [item for p in prepared for item in triage_items(p.pillar1)]
    written: list[Path] = []
    for model in models:
        for index, start in enumerate(range(0, len(items), batch_size), start=1):
            name = f"triage_{index:03d}"
            results_path = (run_dir / "results" / model / f"{name}.jsonl").resolve()
            if results_path.exists():
                continue
            batch_path = run_dir / "batches" / model / f"{name}.md"
            batch_path.parent.mkdir(parents=True, exist_ok=True)
            batch_path.write_text(
                render_triage_batch(items[start : start + batch_size], results_path),
                encoding="utf-8",
            )
            written.append(batch_path)
    return written


def _metrics(
    outcomes: list[CaseOutcome], latencies: list[float], invalid: int
) -> ModelMetrics:
    flagged = [o for o in outcomes if o.expected_status in _FLAGGED]
    quiet = [o for o in outcomes if o.expected_status in _QUIET]
    return ModelMetrics(
        n=len(outcomes),
        accuracy=_ratio(
            sum(o.final_status == o.expected_status for o in outcomes), len(outcomes)
        ),
        false_alarm_rate=_ratio(
            sum(o.final_status in _FLAGGED for o in quiet), len(quiet)
        ),
        miss_rate=_ratio(sum(o.final_status in _QUIET for o in flagged), len(flagged)),
        pillar1_accuracy=_ratio(
            sum(o.pillar1_status == o.expected_status for o in outcomes),
            len(outcomes),
        ),
        p50_latency_ms=_percentile(latencies, 0.5),
        p95_latency_ms=_percentile(latencies, 0.95),
        invalid_verdict_lines=invalid,
    )


def _load_prepared(run_dir: Path) -> list[PreparedStealth]:
    lines = (run_dir / "prepared.jsonl").read_text(encoding="utf-8").splitlines()
    return [PreparedStealth.model_validate_json(x) for x in lines if x.strip()]


def ingest(run_dir: Path) -> dict[str, ModelMetrics]:
    manifest = Manifest.model_validate_json(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    prepared = _load_prepared(run_dir)
    latencies = [p.pillar1.scan_latency_ms for p in prepared]
    outcomes: list[CaseOutcome] = []
    metrics: dict[str, ModelMetrics] = {}
    for model in manifest.models:
        verdicts, invalid = read_verdicts(run_dir, model)
        model_outcomes: list[CaseOutcome] = []
        for p in prepared:
            final = apply_triage(p.pillar1, _verdicts_for(p.pillar1, verdicts))
            model_outcomes.append(
                CaseOutcome(
                    case_id=p.case.case_id,
                    model=model,
                    expected_status=p.case.expected_status,
                    pillar1_status=p.pillar1.stealth_status,
                    final_status=final.stealth_status,
                    final=final,
                )
            )
        metrics[model] = _metrics(model_outcomes, latencies, invalid)
        outcomes.extend(model_outcomes)
    (run_dir / "results.jsonl").write_text(
        "".join(o.model_dump_json() + "\n" for o in outcomes), encoding="utf-8"
    )
    (run_dir / "report.html").write_text(
        render_report(prepared, metrics, outcomes), encoding="utf-8"
    )
    return metrics


def _verdicts_for(
    result: ScanResult, verdicts: dict[str, TriageVerdict]
) -> dict[str, TriageVerdict]:
    return {fid: verdicts[fid] for fid, _ in triage_items(result) if fid in verdicts}


_STYLE = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--card:#f6f6f6;--bad:#b3261e;--ok:#1b6e3c}
@media (prefers-color-scheme: dark){:root{--bg:#141414;--fg:#e6e6e6;--muted:#9a9a9a;--line:#333;--card:#1e1e1e;--bad:#ff8a80;--ok:#7fd69b}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
pre{background:var(--card);padding:6px;white-space:pre-wrap;word-break:break-all;margin:2px 0}
.bad{color:var(--bad)}.ok{color:var(--ok)}.muted{color:var(--muted)}
"""


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_report(
    prepared: list[PreparedStealth],
    metrics: dict[str, ModelMetrics],
    outcomes: list[CaseOutcome] | None = None,
) -> str:
    esc = html.escape
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Stealth triage report</title><style>{_STYLE}</style></head><body>",
        "<h1>Stealth triage report</h1>",
        (
            "<table><tr><th>Model</th><th>N</th><th>Accuracy</th><th>Pillar 1 only</th>"
            "<th>False alarm</th><th>Miss</th><th>P1 p50 ms</th><th>P1 p95 ms</th>"
            "<th>Invalid lines</th></tr>"
        ),
    ]
    for model, m in metrics.items():
        parts.append(
            f"<tr><td>{esc(model)}</td><td>{m.n}</td><td>{_pct(m.accuracy)}</td>"
            f"<td>{_pct(m.pillar1_accuracy)}</td><td>{_pct(m.false_alarm_rate)}</td>"
            f"<td>{_pct(m.miss_rate)}</td><td>{m.p50_latency_ms:.2f}</td>"
            f"<td>{m.p95_latency_ms:.2f}</td><td>{m.invalid_verdict_lines}</td></tr>"
        )
    parts.append("</table><h2>Cases</h2>")
    by_case: dict[str, list[CaseOutcome]] = {}
    for outcome in outcomes or []:
        by_case.setdefault(outcome.case_id, []).append(outcome)
    for p in prepared:
        parts.append(
            f"<h3>{esc(p.case.case_id)} <span class='muted'>{esc(p.case.lang)} / "
            f"{esc(p.case.bucket)} / {esc(p.case.provenance)}</span></h3>"
            f"<div>expected {esc(p.case.expected_status)}, Pillar 1 "
            f"{esc(p.pillar1.stealth_status)}</div>"
        )
        for outcome in by_case.get(p.case.case_id, []):
            css = "ok" if outcome.final_status == outcome.expected_status else "bad"
            parts.append(
                f"<div class='{css}'>{esc(outcome.model)}: "
                f"{esc(outcome.final_status)}</div>"
            )
        for finding in p.pillar1.hidden_findings:
            parts.append(
                f"<div class='muted'>{esc(finding.vector_type)} / "
                f"{esc(finding.classification)}</div>"
                f"<pre>{esc(make_visible(finding.raw_snippet))}</pre>"
            )
            if finding.decoded_hidden_text:
                parts.append(
                    f"<pre>decoded: {esc(make_visible(finding.decoded_hidden_text))}</pre>"
                )
    parts.append("</body></html>")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m palimpsest.stealth.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--cases", type=Path, nargs="+", required=True)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--models", nargs="+", default=["haiku"])
    prep.add_argument("--batch-size", type=int, default=40)
    ing = sub.add_parser("ingest")
    ing.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        written = prepare(args.cases, args.run, args.models, args.batch_size)
        print(f"wrote {len(written)} triage batch files under {args.run / 'batches'}")
    else:
        for model, m in ingest(args.run).items():
            print(f"{model}: {m.model_dump_json()}")


if __name__ == "__main__":
    main()
