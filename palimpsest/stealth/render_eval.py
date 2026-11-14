"""Pillar 3 evaluation: render pages, collect findings, triage them, score.

Two inputs:
- synthetic pages (eval/stealth/render_cases/*.jsonl, HTML + expected label);
- real cited URLs from the bias eval cases, rendered live, with the cached Exa
  text as the text the judge would have seen.
"""

import argparse
import asyncio
import json
import random
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ValidationError

from palimpsest.schema import load_cases
from palimpsest.sources import SourceFetcher
from palimpsest.stage0 import extract_ref_urls
from palimpsest.stealth.models import HiddenFinding
from palimpsest.stealth.pillar3 import judged_drift, render_findings
from palimpsest.stealth.render import (
    PageRenderer,
    RenderAudit,
    RenderBlockedError,
    RenderedTile,
)
from palimpsest.stealth.triage import read_verdicts, render_triage_batch
from palimpsest.stealth.vision import (
    read_vision_verdicts,
    render_vision_batch,
    vision_finding,
    vision_tiles,
)

Expected = Literal["ATTACK", "BENIGN", "IMAGE_TEXT", "REAL"]
PLANTED_RECOVERY: Final = 0.6
_TOKEN: Final = re.compile(r"\w+")


class PageCase(BaseModel):
    case_id: str
    lang: str = ""
    html: str = ""
    url: str | None = None
    expected: Expected
    planted_text: str = ""
    notes: str = ""


class RenderedCase(BaseModel):
    case: PageCase
    error: str | None = None
    findings: list[HiddenFinding] = []
    planted_recovered: bool = False
    hidden_node_count: int = 0
    tile_count: int = 0
    truncated: bool = False
    render_ms: float = 0.0
    judged_drift: float | None = None
    audit: RenderAudit | None = None


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def planted_recovered(planted: str, findings: Sequence[HiddenFinding]) -> bool:
    want = _tokens(planted)
    if not want:
        return False
    found: set[str] = set()
    for finding in findings:
        found |= _tokens(finding.decoded_hidden_text)
    return len(want & found) / len(want) >= PLANTED_RECOVERY


def real_url_cases(
    case_files: list[Path], limit: int, seed: int, fetcher: SourceFetcher
) -> list[PageCase]:
    """Cited URLs whose Exa text is cached, so the judged text is known."""
    urls: list[str] = []
    for path in case_files:
        for case in load_cases(path):
            for url in extract_ref_urls(case.new_wikitext or case.new_text):
                if (
                    url.startswith("http")
                    and url not in urls
                    and fetcher.cached_text(url) is not None
                ):
                    urls.append(url)
    random.Random(seed).shuffle(urls)
    return [
        PageCase(case_id=f"real-{i:03d}", url=url, expected="REAL")
        for i, url in enumerate(urls[:limit])
    ]


async def _render_all(
    cases: list[PageCase], run_dir: Path, fetcher: SourceFetcher
) -> list[RenderedCase]:
    out: list[RenderedCase] = []
    async with PageRenderer() as renderer:
        for case in cases:
            tiles_dir = run_dir / "tiles" / case.case_id
            try:
                audit: RenderAudit
                judged: str | None
                if case.url is not None:
                    audit = await renderer.audit_url(case.url, tiles_dir)
                    judged = fetcher.cached_text(case.url)
                else:
                    audit = await renderer.audit_html(case.html, tiles_dir)
                    # Worst case for a scraper: it ingests every DOM text node.
                    judged = audit.scraper_text
            except (RenderBlockedError, TimeoutError, OSError) as exc:
                out.append(RenderedCase(case=case, error=type(exc).__name__))
                continue
            except Exception as exc:  # noqa: BLE001 - Playwright raises its own Error types
                out.append(
                    RenderedCase(case=case, error=f"{type(exc).__name__}: {exc}"[:200])
                )
                continue
            findings = render_findings(audit, judged)
            out.append(
                RenderedCase(
                    case=case,
                    findings=findings,
                    planted_recovered=planted_recovered(case.planted_text, findings),
                    hidden_node_count=len(audit.hidden_nodes),
                    tile_count=len(audit.tiles),
                    truncated=audit.truncated,
                    render_ms=audit.render_ms,
                    judged_drift=None
                    if judged is None or case.url is None
                    else judged_drift(audit, judged),
                    audit=audit,
                )
            )
    return out


def prepare(
    page_files: list[Path],
    real_case_files: list[Path],
    real_limit: int,
    run_dir: Path,
    model: str,
    batch_size: int,
) -> int:
    cases: list[PageCase] = []
    for path in page_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(PageCase.model_validate_json(line))
    fetcher = SourceFetcher(None, Path("cache/exa"))
    if real_case_files:
        cases.extend(real_url_cases(real_case_files, real_limit, 1114, fetcher))
    rendered = asyncio.run(_render_all(cases, run_dir, fetcher))
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prepared.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in rendered), encoding="utf-8"
    )
    items = [
        (f"{r.case.case_id}:{i}", f) for r in rendered for i, f in enumerate(r.findings)
    ]
    batches = 0
    for start in range(0, len(items), batch_size):
        batches += 1
        name = f"triage_{batches:03d}"
        results_path = (run_dir / "results" / model / f"{name}.jsonl").resolve()
        batch_path = run_dir / "batches" / model / f"{name}.md"
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        batch_path.write_text(
            render_triage_batch(items[start : start + batch_size], results_path),
            encoding="utf-8",
        )
    return batches


class CaseOutcome(BaseModel):
    case_id: str
    expected: Expected
    error: str | None
    deterministic_hit: bool
    planted_recovered: bool
    flagged: bool
    findings: int
    flag_reasons: list[str]
    render_ms: float


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def ingest(run_dir: Path, model: str) -> dict[str, float | int | None]:
    rendered = [
        RenderedCase.model_validate_json(line)
        for line in (run_dir / "prepared.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    verdicts, invalid = read_verdicts(run_dir, model)
    outcomes: list[CaseOutcome] = []
    for r in rendered:
        reasons: list[str] = []
        for i, finding in enumerate(r.findings):
            v = verdicts.get(f"{r.case.case_id}:{i}")
            if v is not None and (
                v.is_prompt_injection or v.is_narrative_or_seo_cloaking
            ):
                reasons.append(
                    f"{finding.vector_type}: {finding.decoded_hidden_text[:80]}"
                )
        outcomes.append(
            CaseOutcome(
                case_id=r.case.case_id,
                expected=r.case.expected,
                error=r.error,
                deterministic_hit=bool(r.findings),
                planted_recovered=r.planted_recovered,
                flagged=bool(reasons),
                findings=len(r.findings),
                flag_reasons=reasons,
                render_ms=r.render_ms,
            )
        )
    (run_dir / "results.jsonl").write_text(
        "".join(o.model_dump_json() + "\n" for o in outcomes), encoding="utf-8"
    )

    def of(kind: Expected) -> list[CaseOutcome]:
        return [o for o in outcomes if o.expected == kind and o.error is None]

    attacks, benign, images, real = (
        of("ATTACK"),
        of("BENIGN"),
        of("IMAGE_TEXT"),
        of("REAL"),
    )
    times = sorted(o.render_ms for o in outcomes if o.error is None)
    return {
        "attack_n": len(attacks),
        "attack_planted_recovered": _ratio(
            sum(o.planted_recovered for o in attacks), len(attacks)
        ),
        "attack_flagged": _ratio(sum(o.flagged for o in attacks), len(attacks)),
        "benign_n": len(benign),
        "benign_with_findings": _ratio(
            sum(o.deterministic_hit for o in benign), len(benign)
        ),
        "benign_flagged": _ratio(sum(o.flagged for o in benign), len(benign)),
        "image_text_n": len(images),
        "image_text_flagged": _ratio(sum(o.flagged for o in images), len(images)),
        "real_n": len(real),
        "real_errors": sum(
            o.error is not None for o in outcomes if o.expected == "REAL"
        ),
        "real_with_findings": _ratio(sum(o.deterministic_hit for o in real), len(real)),
        "real_flagged": _ratio(sum(o.flagged for o in real), len(real)),
        "p50_render_ms": times[len(times) // 2] if times else None,
        "invalid_verdict_lines": invalid,
    }


def _load_rendered(run_dir: Path) -> list[RenderedCase]:
    return [
        RenderedCase.model_validate_json(line)
        for line in (run_dir / "prepared.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def vision_prepare(run_dir: Path, model: str, real_pages: int, batch_size: int) -> int:
    """Batch the image-bearing tiles of synthetic pages and the first real pages."""
    items: list[tuple[str, RenderedTile]] = []
    real_used = 0
    for r in _load_rendered(run_dir):
        if r.audit is None:
            continue
        tiles = vision_tiles(r.audit)
        if not tiles:
            continue
        if r.case.expected == "REAL":
            if real_used >= real_pages:
                continue
            real_used += 1
        items.extend((f"{r.case.case_id}:t{t.index}", t) for t in tiles)
    batches = 0
    for start in range(0, len(items), batch_size):
        batches += 1
        name = f"vision_{batches:03d}"
        results_path = (run_dir / "vision_results" / model / f"{name}.jsonl").resolve()
        batch_path = run_dir / "batches" / model / f"{name}.md"
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        batch_path.write_text(
            render_vision_batch(items[start : start + batch_size], results_path),
            encoding="utf-8",
        )
    return batches


def vision_ingest(run_dir: Path, model: str) -> dict[str, float | int | None]:
    verdicts, invalid = read_vision_verdicts(run_dir / "vision_results" / model)
    flagged_pages: dict[str, list[str]] = {}
    for item_id, verdict in verdicts.items():
        finding = vision_finding(verdict)
        if finding is not None:
            flagged_pages.setdefault(item_id.split(":")[0], []).append(
                finding.decoded_hidden_text[:80]
            )
    seen_pages = {item_id.split(":")[0] for item_id in verdicts}
    expected = {r.case.case_id: r.case.expected for r in _load_rendered(run_dir)}
    planted = {r.case.case_id: r.case.planted_text for r in _load_rendered(run_dir)}

    def pages(kind: Expected) -> list[str]:
        return [p for p in seen_pages if expected.get(p) == kind]

    images, benign, real = pages("IMAGE_TEXT"), pages("BENIGN"), pages("REAL")
    for page, texts in sorted(flagged_pages.items()):
        print(page, expected.get(page), texts, "| planted:", planted.get(page, "")[:60])
    return {
        "image_text_pages": len(images),
        "image_text_flagged": _ratio(
            sum(p in flagged_pages for p in images), len(images)
        ),
        "benign_pages": len(benign),
        "benign_flagged": _ratio(sum(p in flagged_pages for p in benign), len(benign)),
        "real_pages": len(real),
        "real_flagged": _ratio(sum(p in flagged_pages for p in real), len(real)),
        "tiles_judged": len(verdicts),
        "invalid_verdict_lines": invalid,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--pages", type=Path, nargs="*", default=[])
    prep.add_argument("--real-from", type=Path, nargs="*", default=[])
    prep.add_argument("--real-limit", type=int, default=40)
    prep.add_argument("--run", type=Path, required=True)
    prep.add_argument("--model", default="haiku")
    prep.add_argument("--batch-size", type=int, default=60)
    ing = sub.add_parser("ingest")
    ing.add_argument("--run", type=Path, required=True)
    ing.add_argument("--model", default="haiku")
    vprep = sub.add_parser("vision-prepare")
    vprep.add_argument("--run", type=Path, required=True)
    vprep.add_argument("--model", default="sonnet")
    vprep.add_argument("--real-pages", type=int, default=8)
    vprep.add_argument("--batch-size", type=int, default=8)
    ving = sub.add_parser("vision-ingest")
    ving.add_argument("--run", type=Path, required=True)
    ving.add_argument("--model", default="sonnet")
    args = parser.parse_args()
    if args.command == "vision-prepare":
        n = vision_prepare(args.run, args.model, args.real_pages, args.batch_size)
        print(f"wrote {n} vision batch files under {args.run / 'batches'}")
    elif args.command == "vision-ingest":
        print(json.dumps(vision_ingest(args.run, args.model)))
    elif args.command == "prepare":
        n = prepare(
            args.pages,
            args.real_from,
            args.real_limit,
            args.run,
            args.model,
            args.batch_size,
        )
        print(f"wrote {n} triage batch files under {args.run / 'batches'}")
    else:
        try:
            print(json.dumps(ingest(args.run, args.model)))
        except ValidationError as exc:
            raise SystemExit(f"bad prepared.jsonl: {exc}") from exc


if __name__ == "__main__":
    main()
