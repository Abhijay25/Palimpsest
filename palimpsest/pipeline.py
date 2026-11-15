"""Pipeline orchestration: Stage 0 -> Stage 1 -> batch files."""

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from palimpsest.backends.gemini import GeminiJudgeBackend, GeminiReviewerBackend
from palimpsest.context_reads import (
    ContextMode,
    ContextReadBudget,
    append_highlights,
    candidate_for_output,
    linked_page_evidence,
    read_more,
)
from palimpsest.guided import apply_value_swap_rule
from palimpsest.judge import (
    PROMPT_VERSION,
    PROMPTS_DIR,
    FileExchangeBackend,
    PreparedCase,
    judge_with_latencies,
)
from palimpsest.report import render_report
from palimpsest.reviewer import (
    ReviewerCandidate,
    ReviewerResult,
    review_candidates,
    review_unit_eligible,
)
from palimpsest.schema import (
    AuditOutput,
    Case,
    CaseResult,
    ExpandDirection,
    Flag,
    FlagEvidence,
    FlaggedSpan,
    Guideline,
    SourceWindow,
    Verdict,
    dump_jsonl,
    load_cases,
)
from palimpsest.scoring import score
from palimpsest.sources import SourceFetcher, load_exa_api_key
from palimpsest.stage0 import (
    changed_claim_has_added_citation,
    changed_region_has_citation,
    prefilter,
    strip_wikitext,
)
from palimpsest.stealth.models import ScanResult, StealthStatus
from palimpsest.stealth.scanner import reportable_findings, scan, worst_status
from palimpsest.value_check import check_case
from palimpsest.value_swaps import swaps

STAGE1_CONCURRENCY: Final = 8
MAX_SOURCE_URLS: Final = 3
CACHE_DIR: Final = Path("cache/exa")


class Manifest(BaseModel):
    prompt_version: str
    models: list[str]
    case_files: list[str]
    source_mode: Literal["highlights", "lexical"] = "highlights"
    followup: bool = False
    context_mode: ContextMode = "rule"


def _ref_scanner(
    ref_scans: list[ScanResult] | None,
) -> Callable[[str], str | None] | None:
    """Scan fetched page text; withhold pages flagged CRITICAL from windowing."""
    if ref_scans is None:
        return None

    def on_text(text: str) -> str | None:
        result = scan(text, "EXTERNAL_REF_PAGE")
        ref_scans.append(result)
        if result.stealth_status == StealthStatus.CRITICAL_AI_POISONING:
            return None
        return result.sanitized_human_text

    return on_text


def _worst_scan(scans: list[ScanResult]) -> ScanResult | None:
    if not scans:
        return None
    worst = worst_status(s.stealth_status for s in scans)
    return next(s for s in scans if s.stealth_status == worst)


def _sanitized(text: str) -> tuple[str, float]:
    result = scan(text, "WIKIPEDIA_DIFF")
    return result.sanitized_human_text, result.scan_latency_ms


async def _window_for(
    case: Case,
    fetcher: SourceFetcher,
    ref_scans: list[ScanResult] | None = None,
    source_mode: Literal["highlights", "lexical"] = "highlights",
) -> SourceWindow:
    if case.source_window is not None:
        return SourceWindow(
            url=None, status="fixed", text=case.source_window, latency_ms=0.0
        )
    urls = case.changed_ref_urls or case.ref_urls
    if case.changed_ref_urls is not None and not case.changed_ref_urls:
        has_changed_citation = (
            case.old_wikitext is not None
            and case.new_wikitext is not None
            and changed_region_has_citation(case.old_wikitext, case.new_wikitext)
        )
        if not has_changed_citation:
            return SourceWindow(url=None, status="uncited", text="", latency_ms=0.0)
    claim = strip_wikitext(case.new_text)
    old_claim = strip_wikitext(case.old_text)
    scored_all = await asyncio.gather(
        *(
            fetcher.window_scored(
                url,
                claim,
                on_text=_ref_scanner(ref_scans),
                old_claim=old_claim,
                source_mode=source_mode,
            )
            for url in sorted(urls)[:MAX_SOURCE_URLS]
        )
    )
    best: tuple[SourceWindow, int] | None = None
    for scored in scored_all:
        if scored[0].status == "ok" and (best is None or scored[1] > best[1]):
            best = scored
    if best is not None:
        return best[0]
    return SourceWindow(url=None, status="unavailable", text="", latency_ms=0.0)


async def prepare(
    cases_paths: list[Path],
    run_dir: Path,
    models: list[str],
    prompt_version: str = PROMPT_VERSION,
    batch_size: int = 10,
    backend: str = "file",
    gemini_backend: GeminiJudgeBackend | None = None,
    source_mode: Literal["highlights", "lexical"] = "highlights",
    followup: bool = False,
    context_mode: ContextMode = "rule",
    value_check: bool = True,
    reviewer: bool = False,
    reviewer_backend: GeminiReviewerBackend | None = None,
) -> None:
    if not (PROMPTS_DIR / f"{prompt_version}.txt").is_file():
        raise SystemExit(f"unknown prompt version: {prompt_version}")
    if backend not in ("file", "gemini"):
        raise SystemExit(f"unknown backend: {backend}")
    if backend == "gemini" and gemini_backend is None:
        gemini_backend = GeminiJudgeBackend(prompt_version=prompt_version)
    if reviewer and backend != "gemini":
        raise SystemExit("--reviewer requires --backend gemini")
    if reviewer and reviewer_backend is None:
        reviewer_backend = GeminiReviewerBackend()
    cases: dict[str, Case] = {}
    for path in cases_paths:
        for case in load_cases(path):
            cases.setdefault(case.case_id, case)
    fetcher = SourceFetcher(load_exa_api_key(), CACHE_DIR)
    semaphore = asyncio.Semaphore(STAGE1_CONCURRENCY)

    async def prepare_one(case: Case) -> PreparedCase:
        diff_scan = scan(
            case.new_wikitext or case.new_text,
            "WIKIPEDIA_DIFF",
            old_text=case.old_wikitext or case.old_text,
        )
        old_text, old_ms = _sanitized(case.old_text)
        new_text, new_ms = _sanitized(case.new_text)
        stealth_ms = diff_scan.scan_latency_ms + old_ms + new_ms
        case = case.model_copy(update={"old_text": old_text, "new_text": new_text})
        value_report = await check_case(case, fetcher) if value_check else None
        stage0 = prefilter(case.old_text, case.new_text, case.lang)
        if stage0.clean:
            return PreparedCase(
                case=case,
                stage0=stage0,
                window=None,
                diff_scan=diff_scan,
                stealth_ms=stealth_ms,
                value_check=value_report,
            )
        ref_scans: list[ScanResult] = []
        async with semaphore:
            window = await _window_for(case, fetcher, ref_scans, source_mode)
            linked_evidence = await linked_page_evidence(
                strip_wikitext(case.new_text),
                case.new_wikitext or case.new_text,
                case.lang,
                fetcher,
            )
        return PreparedCase(
            case=case,
            stage0=stage0,
            window=window,
            diff_scan=diff_scan,
            ref_scan=_worst_scan(ref_scans),
            stealth_ms=stealth_ms + sum(s.scan_latency_ms for s in ref_scans),
            value_check=value_report,
            linked_evidence=linked_evidence,
        )

    prepared = list(await asyncio.gather(*(prepare_one(c) for c in cases.values())))
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_jsonl(run_dir / "prepared.jsonl", prepared)
    if gemini_backend is not None:
        models = [gemini_backend.model]
    manifest = Manifest(
        prompt_version=prompt_version,
        models=models,
        case_files=[str(p) for p in cases_paths],
        source_mode=source_mode,
        followup=followup,
        context_mode=context_mode,
    )
    (run_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    if gemini_backend is not None:
        await _judge_with_gemini(
            gemini_backend,
            prepared,
            run_dir,
            fetcher,
            reviewer_backend,
            context_mode,
            followup,
        )
        batches: list[Path] = []
    else:
        batches = FileExchangeBackend().write_batches(
            prepared,
            run_dir,
            models,
            batch_size=batch_size,
            prompt_version=prompt_version,
        )
    print(f"Exa calls: {fetcher.calls}, cost ${fetcher.cost_dollars:.4f}")
    if gemini_backend is not None:
        print(f"Gemini usage ({gemini_backend.model}): {gemini_backend.usage}")
    if reviewer_backend is not None:
        print(f"Gemini usage ({reviewer_backend.model}): {reviewer_backend.usage}")
    clean = sum(1 for pc in prepared if pc.stage0.clean)
    print(
        f"{len(prepared)} cases, {clean} stage-0 clean, "
        f"{len(batches)} batch files in {run_dir / 'batches'}"
    )


def _review_flag(pc: PreparedCase, output: AuditOutput, index: int) -> Flag:
    span = output.flagged_spans[index]
    kind = {
        Verdict.FLAG_G1_FACT: "FACT",
        Verdict.FLAG_G2_FRAMING: "FRAMING",
        Verdict.FLAG_G3_MOTIVE: "MOTIVE",
    }[output.verdict]
    evidence = (
        [FlagEvidence(source="cited", quote=pc.window.text, url=pc.window.url)]
        if pc.window is not None and pc.window.text
        else []
    )
    evidence.extend(pc.linked_evidence)
    return Flag(
        id=f"{pc.case.case_id}-s{index}",
        kind=kind,
        tier="admin" if output.confidence >= 0.70 else "review",
        title="Model finding needs review",
        reason=span.explanation,
        confidence=output.confidence,
        side="new",
        anchor_text=span.exact_substring,
        anchor_start=None,
        anchor_end=None,
        context_sentence=pc.case.new_text,
        evidence=evidence,
        citations=pc.case.changed_ref_urls or pc.case.ref_urls,
        neutral_rewrite=output.neutral_rewrite,
        check="judge",
        before=pc.case.old_text,
        after=pc.case.new_text,
    )


def _borderline_candidate(
    pc: PreparedCase, output: AuditOutput
) -> ReviewerCandidate | None:
    if output.verdict != Verdict.CLEAN_PASS or not swaps(
        pc.case.old_text, pc.case.new_text
    ):
        return None
    if _value_swaps_have_added_citations(pc):
        return None
    return ReviewerCandidate(
        candidate_id=f"{pc.case.case_id}-borderline",
        kind="FACT",
        edit_text=pc.case.new_text,
        old_text=pc.case.old_text,
        source_excerpts=[pc.window.text] if pc.window is not None else [],
        title="Changed claim needs review",
        reason="The changed claim was not clearly supported by the source excerpt.",
        is_value_change=True,
    )


async def _review_output(
    pc: PreparedCase,
    output: AuditOutput,
    fetcher: SourceFetcher,
    backend: GeminiReviewerBackend,
    context_mode: ContextMode = "rule",
) -> tuple[AuditOutput, ReviewerResult]:
    if not review_unit_eligible(output, pc.case.old_text, pc.case.new_text):
        return output, ReviewerResult([], "skipped", 0, 0.0, 0, "no value change")
    flags = [
        _review_flag(pc, output, index) for index in range(len(output.flagged_spans))
    ]
    borderline = _borderline_candidate(pc, output)
    reviewed = await review_candidates(
        page_title=pc.case.page_title,
        language=pc.case.lang,
        flags=flags,
        borderline=[borderline] if borderline is not None else [],
        fetcher=fetcher,
        backend=backend,
        context_mode=context_mode,
    )
    if reviewed.status == "skipped":
        return output, reviewed
    by_id = {flag.id: flag for flag in reviewed.flags}
    replacements = [by_id.get(flag.id, flag).reason for flag in flags]
    spans = [
        span.model_copy(update={"explanation": reason})
        for span, reason in zip(output.flagged_spans, replacements, strict=True)
    ]
    existing_tiers = [by_id.get(flag.id, flag).tier for flag in flags]
    if flags:
        return (
            output.model_copy(
                update={
                    "confidence": (
                        0.65
                        if existing_tiers
                        and all(tier == "review" for tier in existing_tiers)
                        else output.confidence
                    ),
                    "flagged_spans": spans,
                }
            ),
            reviewed,
        )
    raised = next(
        (flag for flag in reviewed.flags if flag.id.startswith("review-")), None
    )
    if raised is None:
        return output, reviewed
    return (
        AuditOutput(
            verdict=Verdict.FLAG_G2_FRAMING,
            confidence=0.65,
            expand_direction=ExpandDirection.NONE,
            atomic_propositions=output.atomic_propositions,
            flagged_spans=[
                FlaggedSpan(
                    exact_substring=raised.anchor_text,
                    guideline_violated=Guideline.G2_FRAMING,
                    explanation=raised.reason,
                )
            ],
            neutral_rewrite=None,
        ),
        reviewed,
    )


async def _judge_with_gemini(
    backend: GeminiJudgeBackend,
    prepared: list[PreparedCase],
    run_dir: Path,
    fetcher: SourceFetcher,
    reviewer_backend: GeminiReviewerBackend | None,
    context_mode: ContextMode,
    followup: bool,
) -> None:
    """Judge inline and write results in the file-exchange format ingest reads."""
    judged, latencies = await judge_with_latencies(
        backend, [pc for pc in prepared if not pc.stage0.clean]
    )
    if followup:
        followup_latencies = await _followup_with_gemini(
            backend, prepared, judged, fetcher, context_mode
        )
        latencies.update(followup_latencies)
    reviewer_rows: list[dict[str, object]] = []
    if reviewer_backend is not None:
        for pc in prepared:
            outcome = judged.get(pc.case.case_id)
            if not isinstance(outcome, AuditOutput):
                continue
            reviewed_output, reviewer = await _review_output(
                pc,
                _apply_value_swap_rule(pc, outcome),
                fetcher,
                reviewer_backend,
                context_mode,
            )
            judged[pc.case.case_id] = reviewed_output
            reviewer_rows.append(
                {
                    "case_id": pc.case.case_id,
                    "status": reviewer.status,
                    "calls": reviewer.calls,
                    "latency_ms": reviewer.latency_ms,
                    "tokens": reviewer.tokens,
                    "error": reviewer.error,
                }
            )
    lines: list[str] = []
    for case_id, outcome in judged.items():
        row: dict[str, object] = {
            "case_id": case_id,
            "stage2_ms": latencies.get(case_id, 0.0),
        }
        if isinstance(outcome, str):
            row["error"] = outcome
        else:
            row["output"] = outcome.model_dump(mode="json")
        lines.append(json.dumps(row))
    path = run_dir / "results" / backend.model / "batch_001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    if reviewer_backend is not None:
        (run_dir / "reviewer.jsonl").write_text(
            "\n".join(json.dumps(row) for row in reviewer_rows)
            + ("\n" if reviewer_rows else ""),
            encoding="utf-8",
        )


async def _followup_with_gemini(
    backend: GeminiJudgeBackend,
    prepared: list[PreparedCase],
    judged: dict[str, AuditOutput | str],
    fetcher: SourceFetcher,
    context_mode: ContextMode,
) -> dict[str, float]:
    """Re-judge only candidates whose policy-approved whole-source query found text."""
    retry: list[PreparedCase] = []
    for pc in prepared:
        outcome = judged.get(pc.case.case_id)
        if (
            not isinstance(outcome, AuditOutput)
            or pc.window is None
            or pc.window.url is None
        ):
            continue
        started = time.perf_counter()
        read = await read_more(
            candidate_for_output(
                outcome, pc.case.new_text, pc.case.changed_ref_urls or pc.case.ref_urls
            ),
            fetcher,
            ContextReadBudget(),
            context_mode,
        )
        pc.window = append_highlights(pc.window, read.passages).model_copy(
            update={
                "latency_ms": pc.window.latency_ms
                + (time.perf_counter() - started) * 1000,
                "whole_source_checked": read.checked,
                "whole_source_passages": read.passages,
                "whole_source_classification": read.classification,
                "whole_source_supports_claim": read.supports_claim,
            }
        )
        if read.passages:
            retry.append(pc)
    if not retry:
        return {}
    retried, latencies = await judge_with_latencies(backend, retry)
    judged.update(retried)
    return latencies


def _stage0_clean_output() -> AuditOutput:
    return AuditOutput(
        verdict=Verdict.CLEAN_PASS,
        confidence=1.0,
        expand_direction=ExpandDirection.NONE,
        atomic_propositions=[],
        flagged_spans=[],
        neutral_rewrite=None,
    )


def _scans(pc: PreparedCase) -> list[ScanResult]:
    return [s for s in (pc.diff_scan, pc.ref_scan) if s is not None]


def _stealth_status(pc: PreparedCase) -> str | None:
    scans = _scans(pc)
    if not scans:
        return None
    return worst_status(s.stealth_status for s in scans).value


def _stealth_vectors(pc: PreparedCase) -> list[str]:
    return sorted(
        {f.vector_type.value for s in _scans(pc) for f in reportable_findings(s)}
    )


def _citation_backs_claim(pc: PreparedCase, claim: str) -> bool:
    old_wikitext = pc.case.old_wikitext
    new_wikitext = pc.case.new_wikitext
    return (
        changed_claim_has_added_citation(old_wikitext, new_wikitext, claim)
        if old_wikitext is not None and new_wikitext is not None
        else False
    )


def _value_swaps_have_added_citations(pc: PreparedCase) -> bool:
    value_swaps = swaps(pc.case.old_text, pc.case.new_text)
    return bool(value_swaps) and all(
        _citation_backs_claim(pc, new_value)
        for change in value_swaps
        for _, new_value in change.pairs
    )


def _apply_value_swap_rule(pc: PreparedCase, output: AuditOutput) -> AuditOutput:
    """Do not label a value swap unsourced when its changed sentence adds a citation."""
    return apply_value_swap_rule(
        output,
        pc.case.old_text,
        pc.case.new_text,
        lambda claim: _citation_backs_claim(pc, claim),
    )


def _case_result(
    pc: PreparedCase,
    model: str,
    judged: dict[str, AuditOutput | str],
    prompt_version: str,
    stage2_ms: float = 0.0,
) -> CaseResult:
    window = pc.window
    base = {
        "case_id": pc.case.case_id,
        "model": model,
        "prompt_version": prompt_version,
        "stage0_ms": pc.stage0.latency_ms,
        "stage1_ms": window.latency_ms if window else 0.0,
        "source_status": window.status if window else "skipped",
        "stealth_status": _stealth_status(pc),
        "stealth_vectors": _stealth_vectors(pc),
        "stealth_ms": pc.stealth_ms,
        "stage2_ms": 0.0 if pc.stage0.clean else stage2_ms,
    }
    if pc.stage0.clean:
        return CaseResult(
            **base, stage_reached=0, output=_stage0_clean_output(), parse_error=None
        )
    outcome = judged.get(pc.case.case_id, "no result line for this case")
    if isinstance(outcome, str):
        return CaseResult(**base, stage_reached=1, output=None, parse_error=outcome)
    return CaseResult(
        **base,
        stage_reached=2,
        output=_apply_value_swap_rule(pc, outcome),
        parse_error=None,
    )


def ingest(run_dir: Path, compare_to: Path | None = None) -> None:
    prepared = [
        PreparedCase.model_validate_json(line)
        for line in (run_dir / "prepared.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    backend = FileExchangeBackend()
    prepared_by_id = {pc.case.case_id: pc for pc in prepared}
    results: dict[str, list[CaseResult]] = {}
    for model in manifest.models:
        judged = backend.read_results(run_dir, model, prepared_by_id)
        stage2_ms = backend.read_stage2_ms(run_dir, model)
        results[model] = [
            _case_result(
                pc,
                model,
                judged,
                manifest.prompt_version,
                stage2_ms.get(pc.case.case_id, 0.0),
            )
            for pc in prepared
        ]
    metrics = score(prepared, results)
    dump_jsonl(
        run_dir / "results.jsonl", [r for rows in results.values() for r in rows]
    )
    path = render_report(run_dir, prepared, results, metrics, compare_to)
    for model, m in metrics.items():
        print(
            f"{model}: recall={m.violation_recall:.0%} clean_flag={m.clean_flag_rate:.0%} "
            f"parse_err={m.parse_error_rate:.0%} pass={m.passes_bar}"
        )
    print(f"report: {path}")
