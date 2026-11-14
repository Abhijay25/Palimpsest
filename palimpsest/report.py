"""Static HTML report (inline CSS, light/dark via prefers-color-scheme)."""

import difflib
import html
from collections.abc import Callable
from pathlib import Path
from typing import Final

from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput, CaseResult, FlaggedSpan, Verdict
from palimpsest.scoring import (
    ADMIN_THRESHOLD,
    FLAGS,
    REVIEW_THRESHOLD,
    Metrics,
    route,
)
from palimpsest.stealth.models import StealthStatus
from palimpsest.stealth.scanner import reportable_findings

NO_LINK_BUCKET_MARKERS: Final = ("spec", "synthetic", "wnc")

CSS: Final = """
:root{color-scheme:light dark;--bg:#fafafa;--fg:#1c1c1e;--card:#fff;--line:#d8d8de;
--muted:#6b6b76;--ins:#cdeccd;--del:#f6cccc;--mark:#ffe58a;--ok:#1f7a3a;--bad:#b3261e;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--fg:#e6e6ea;--card:#1c1c20;
--line:#34343c;--muted:#9a9aa6;--ins:#1f4a2a;--del:#5a2323;--mark:#6b5a10;--ok:#6fd48c;
--bad:#ff8a80;--warn:#e3b341}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:980px;
margin:0 auto;padding:16px}
table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid var(--line);padding:4px 8px;
text-align:left;font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;
margin:14px 0}
.card.wrong{border-left:5px solid var(--bad)}.meta{color:var(--muted);font-size:13px}
.text{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);padding:6px 8px;
border-radius:4px}
ins{background:var(--ins);text-decoration:none}del{background:var(--del)}
mark{background:var(--mark);color:inherit}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;border:1px solid var(--line);
font-size:12px;font-weight:600}.pass{color:var(--ok)}.fail{color:var(--bad)}.warn{color:var(--warn)}
details{margin:6px 0}summary{cursor:pointer}.model{border-top:1px dashed var(--line);
margin-top:8px;padding-top:6px}
"""


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def word_diff_html(old: str, new: str) -> str:
    old_words, new_words = old.split(), new.split()
    parts: list[str] = []
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(_e(" ".join(old_words[i1:i2])))
            continue
        if i2 > i1:
            parts.append(f"<del>{_e(' '.join(old_words[i1:i2]))}</del>")
        if j2 > j1:
            parts.append(f"<ins>{_e(' '.join(new_words[j1:j2]))}</ins>")
    return " ".join(p for p in parts if p)


def highlight_spans(
    text: str, spans: list[FlaggedSpan]
) -> tuple[str, list[FlaggedSpan]]:
    """Return escaped HTML with matched spans marked, plus the spans not found."""
    ranges: list[tuple[int, int, FlaggedSpan]] = []
    unmatched: list[FlaggedSpan] = []
    for span in spans:
        start = text.find(span.exact_substring) if span.exact_substring else -1
        end = start + len(span.exact_substring)
        if start < 0 or any(start < e and end > s for s, e, _ in ranges):
            unmatched.append(span)
        else:
            ranges.append((start, end, span))
    ranges.sort(key=lambda r: r[0])
    out: list[str] = []
    cursor = 0
    for start, end, span in ranges:
        out.append(_e(text[cursor:start]))
        title = _e(f"{span.guideline_violated.value}: {span.explanation}")
        out.append(f'<mark title="{title}">{_e(text[start:end])}</mark>')
        cursor = end
    out.append(_e(text[cursor:]))
    return "".join(out), unmatched


def _verdict_badge(result: CaseResult | None) -> str:
    if result is None:
        return '<span class="badge">no result</span>'
    if result.output is None:
        return '<span class="badge fail">PARSE_ERROR</span>'
    verdict = result.output.verdict
    css = (
        "fail"
        if verdict in FLAGS
        else "warn"
        if verdict == Verdict.EXPAND_CONTEXT
        else "pass"
    )
    return (
        f'<span class="badge {css}">{verdict.value}</span> '
        f"<span class=meta>conf {result.output.confidence:.2f}</span>"
    )


def _route_badge(result: CaseResult | None) -> str:
    if result is None:
        return ""
    queue = route(result)
    css = {"admin": "fail", "review": "warn", "none": ""}[queue]
    return f' <span class="badge {css}">route: {queue}</span>'


def _model_block(model: str, result: CaseResult | None, new_text: str) -> str:
    parts = [
        f'<div class="model"><b>{_e(model)}</b> {_verdict_badge(result)}{_route_badge(result)}'
    ]
    if result is not None and result.output is None:
        parts.append(f'<div class="meta">{_e(result.parse_error or "")}</div>')
    if result is not None and result.output is not None:
        output: AuditOutput = result.output
        marked, unmatched = highlight_spans(new_text, output.flagged_spans)
        parts.append(f'<div class="text">{marked}</div>')
        for span in unmatched:
            parts.append(
                f'<div class="meta">Unmatched span ({_e(span.guideline_violated.value)}): '
                f"<code>{_e(span.exact_substring)}</code> &mdash; {_e(span.explanation)}</div>"
            )
        if output.atomic_propositions:
            rows = "".join(
                f"<tr><td>{_e(p.clause_text)}</td><td>{p.clause_type.value}</td>"
                f"<td>{p.source_entailment.value}</td>"
                f"<td>{_e(p.evidence_quote_from_ref or '')}</td></tr>"
                for p in output.atomic_propositions
            )
            parts.append(
                "<table><tr><th>Clause</th><th>Type</th><th>Entailment</th>"
                f"<th>Evidence</th></tr>{rows}</table>"
            )
        if output.neutral_rewrite:
            parts.append(
                f'<div><span class="meta">Rewrite:</span> {_e(output.neutral_rewrite)}</div>'
            )
    parts.append("</div>")
    return "".join(parts)


def _label(result: CaseResult | None) -> str:
    return result.output.verdict.value if result and result.output else "PARSE_ERROR"


def _sort_tier(pc: PreparedCase, rows: list[CaseResult | None]) -> int:
    labels = [_label(r) for r in rows]
    expected = pc.case.expected
    if expected != "UNLABELLED" and any(lb != expected.value for lb in labels):
        return 0
    if len(set(labels)) > 1:
        return 1
    if any(lb in {v.value for v in FLAGS} for lb in labels):
        return 2
    if Verdict.EXPAND_CONTEXT.value in labels:
        return 3
    return 4


def _stealth_html(pc: PreparedCase) -> str:
    scans = [s for s in (pc.diff_scan, pc.ref_scan) if s is not None]
    flagged = [s for s in scans if s.stealth_status != StealthStatus.CLEAN]
    if not flagged:
        return ""
    parts = []
    for s in flagged:
        findings = "".join(
            f"<li>{_e(f.vector_type.value)}: {_e(f.explanation)} "
            f"<code>{_e(f.decoded_hidden_text or f.raw_snippet)}</code></li>"
            for f in reportable_findings(s)
        )
        parts.append(
            f'<div><span class="badge fail">STEALTH {_e(s.stealth_status.value)}</span> '
            f'<span class="meta">{_e(s.target_type)}</span><ul>{findings}</ul></div>'
        )
    return "".join(parts)


def _case_card(
    pc: PreparedCase,
    models: list[str],
    by_model: dict[str, dict[str, CaseResult]],
    tier: int,
) -> str:
    case = pc.case
    title = _e(case.page_title)
    if case.page_title and not any(m in case.bucket for m in NO_LINK_BUCKET_MARKERS):
        url = f"https://{case.lang}.wikipedia.org/wiki/{case.page_title.replace(' ', '_')}"
        title = f'<a href="{_e(url)}" rel="noreferrer">{title}</a>'
    expected = case.expected if isinstance(case.expected, str) else case.expected.value
    window = pc.window.text if pc.window else ""
    status = pc.window.status if pc.window else "stage-0 clean"
    gloss = (
        f'<div class="meta">EN gloss: {_e(case.en_gloss)}</div>'
        if case.en_gloss
        else ""
    )
    blocks = "".join(
        _model_block(m, by_model[m].get(case.case_id), case.new_text) for m in models
    )
    return (
        f'<div class="card{" wrong" if tier == 0 else ""}" id="{_e(case.case_id)}">'
        f"<b>{_e(case.case_id)}</b> "
        f'<span class="meta">{_e(case.bucket)} · {case.lang} · expected {_e(expected)} · {title}</span>'
        f"{_stealth_html(pc)}"
        f'<div class="text">{word_diff_html(case.old_text, case.new_text)}</div>{gloss}'
        f"<details><summary>Source window ({_e(status)})</summary>"
        f'<div class="text">{_e(window)}</div></details>{blocks}</div>'
    )


def _metrics_table(metrics: dict[str, Metrics]) -> str:
    rows: list[tuple[str, str]] = [
        ("Pass bar", ""),
        ("Cases (labelled)", ""),
        ("Violation recall", ""),
        ("Category accuracy", ""),
        ("Clean flag rate", ""),
        ("Abstain rate", ""),
        ("Parse error rate", ""),
        ("Stage 0 exit rate", ""),
        ("Stage 0 false pass", ""),
        ("Source unavailable", ""),
        ("Uncited", ""),
        ("Stage 0 / 1 p50 ms", ""),
        ("Stealth flagged", ""),
        ("Stealth admin flags", ""),
        ("Admin false alarm rate", ""),
        ("Admin recall", ""),
        ("Review rate", ""),
        ("Unlabelled admin / review", ""),
    ]
    head = "".join(f"<th>{_e(m)}</th>" for m in metrics)

    def cells(fn: Callable[[Metrics], str]) -> str:
        return "".join(f"<td>{fn(m)}</td>" for m in metrics.values())

    def pct(x: float) -> str:
        return f"{x:.0%}"

    values = [
        cells(
            lambda m: (
                '<span class="badge pass">PASS</span>'
                if m.passes_bar
                else '<span class="badge fail">FAIL</span>'
            )
        ),
        cells(lambda m: f"{m.n} ({m.labelled_n})"),
        cells(lambda m: pct(m.violation_recall)),
        cells(lambda m: pct(m.category_accuracy)),
        cells(lambda m: pct(m.clean_flag_rate)),
        cells(lambda m: pct(m.abstain_rate)),
        cells(lambda m: pct(m.parse_error_rate)),
        cells(lambda m: pct(m.stage0_exit_rate)),
        cells(lambda m: str(m.stage0_false_pass)),
        cells(lambda m: pct(m.source_unavailable_rate)),
        cells(lambda m: pct(m.uncited_rate)),
        cells(lambda m: f"{m.stage0_ms_p50:.1f} / {m.stage1_ms_p50:.0f}"),
        cells(lambda m: pct(m.stealth_flag_rate)),
        cells(lambda m: str(m.stealth_flags)),
        cells(lambda m: pct(m.admin_false_alarm_rate)),
        cells(lambda m: pct(m.admin_recall)),
        cells(lambda m: pct(m.review_rate)),
        cells(lambda m: f"{m.unlabelled_admin} / {m.unlabelled_review}"),
    ]
    body = "".join(
        f"<tr><th>{_e(label)}</th>{value}</tr>"
        for (label, _), value in zip(rows, values)
    )
    return f"<table><tr><th></th>{head}</tr>{body}</table>"


_ROUTING_LEGEND: Final = (
    f'<p class="meta">Routing: flag with confidence &ge; {ADMIN_THRESHOLD:.2f} &rarr; admin, '
    f"{REVIEW_THRESHOLD:.2f}&ndash;{ADMIN_THRESHOLD:.2f} &rarr; review, lower &rarr; none; "
    "stealth critical/CSS/homoglyph &rarr; admin. Confidences are self-reported "
    "(uncalibrated) for Claude stand-ins.</p>"
)


def _confusion(metrics: dict[str, Metrics]) -> str:
    out: list[str] = []
    for model, m in metrics.items():
        columns = sorted({c for row in m.confusion.values() for c in row})
        head = "".join(f"<th>{_e(c)}</th>" for c in columns)
        body = "".join(
            f"<tr><th>{_e(exp)}</th>"
            + "".join(f"<td>{row.get(c, 0)}</td>" for c in columns)
            + "</tr>"
            for exp, row in sorted(m.confusion.items())
        )
        out.append(
            f"<details><summary>Confusion: {_e(model)} (rows expected, columns got)</summary>"
            f"<table><tr><th></th>{head}</tr>{body}</table></details>"
        )
    return "".join(out)


def _changes(
    results: dict[str, list[CaseResult]], previous: dict[str, list[CaseResult]]
) -> str:
    items: list[str] = []
    for model, rows in results.items():
        before = {r.case_id: _label(r) for r in previous.get(model, [])}
        for r in rows:
            if r.case_id in before and before[r.case_id] != _label(r):
                items.append(
                    f'<li><a href="#{_e(r.case_id)}">{_e(r.case_id)}</a> '
                    f"({_e(model)}): {_e(before[r.case_id])} &rarr; {_e(_label(r))}</li>"
                )
    body = "".join(items) or "<li>No verdict changes.</li>"
    return f"<h2>Changed since previous run</h2><ul>{body}</ul>"


def _load_previous(run_dir: Path) -> dict[str, list[CaseResult]]:
    previous: dict[str, list[CaseResult]] = {}
    for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = CaseResult.model_validate_json(line)
            previous.setdefault(row.model, []).append(row)
    return previous


def render_report(
    run_dir: Path,
    prepared: list[PreparedCase],
    results: dict[str, list[CaseResult]],
    metrics: dict[str, Metrics],
    compare_to: Path | None = None,
) -> Path:
    models = list(results)
    by_model = {m: {r.case_id: r for r in rows} for m, rows in results.items()}
    tiered = []
    for pc in prepared:
        rows = [by_model[m].get(pc.case.case_id) for m in models]
        tiered.append((_sort_tier(pc, rows), pc))
    tiered.sort(key=lambda t: t[0])
    cards = "".join(_case_card(pc, models, by_model, tier) for tier, pc in tiered)
    changes = ""
    if compare_to is not None:
        changes = _changes(results, _load_previous(compare_to))
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Palimpsest run report</title><style>{CSS}</style></head><body>"
        f"<h1>Palimpsest run report</h1>{_metrics_table(metrics)}{_ROUTING_LEGEND}"
        f"{_confusion(metrics)}"
        f"{changes}<h2>Cases ({len(prepared)})</h2>"
        '<p class="meta">Order: wrong vs expected, model disagreement, flagged, '
        f"EXPAND_CONTEXT, rest.</p>{cards}</body></html>"
    )
    path = run_dir / "report.html"
    path.write_text(document, encoding="utf-8")
    return path
