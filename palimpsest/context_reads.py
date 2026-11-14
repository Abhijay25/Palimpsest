"""Bounded, policy-driven reads beyond the initially cited source excerpt."""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

from palimpsest.schema import AuditOutput, Entailment, Flag, FlagEvidence, SourceWindow

ContextClass = Literal[
    "ABSENCE", "REMOVED_CONTEXT", "CONTRADICTION", "STYLE", "UNCITED"
]
ContextMode = Literal["never", "rule", "always"]

MAX_CALLS_PER_CANDIDATE = 2
MAX_CALLS_PER_REQUEST = 6
CONTEXT_DEADLINE_S = 6.0
_WORD = re.compile(r"[\w'-]+")
_CAUSAL = re.compile(r"\b(?:because|caused|due to|in order to|to\s+\w+)", re.IGNORECASE)
_ABSENCE = re.compile(
    r"\b(?:unsupported|not (?:stated|mentioned|supported|established)|"
    r"source does not|without (?:a )?(?:source|support)|unverified)\b",
    re.IGNORECASE,
)


class HighlightsFetcher(Protocol):
    async def highlights(self, url: str, query: str) -> list[str] | None: ...


@dataclass(frozen=True)
class ContextCandidate:
    """The small, trusted description needed to decide whether to read further."""

    kind: str
    claim: str
    reason: str
    citations: list[str]
    has_validated_contradiction: bool = False


@dataclass
class ContextReadBudget:
    """Shared per-request cap, including the reviewer after the follow-up judge."""

    max_calls: int = MAX_CALLS_PER_REQUEST
    deadline_s: float = CONTEXT_DEADLINE_S
    started: float = field(default_factory=time.monotonic)
    calls: int = 0

    def remaining(self) -> float:
        return self.deadline_s - (time.monotonic() - self.started)

    def acquire(self) -> bool:
        if self.calls >= self.max_calls or self.remaining() <= 0:
            return False
        self.calls += 1
        return True


@dataclass(frozen=True)
class ContextRead:
    classification: ContextClass
    passages: list[str]
    checked: bool
    supports_claim: bool


def classify(candidate: ContextCandidate) -> ContextClass:
    """Classify the evidence basis; this is the only source-read policy switch."""
    if not candidate.citations:
        return "UNCITED"
    if candidate.kind == "REMOVED_CONTEXT":
        return "REMOVED_CONTEXT"
    if candidate.has_validated_contradiction:
        return "CONTRADICTION"
    text = f"{candidate.claim} {candidate.reason}"
    if candidate.kind in {"MOTIVE", "FACT"} or _ABSENCE.search(text):
        return "ABSENCE"
    if candidate.kind == "FRAMING" and _CAUSAL.search(text):
        return "ABSENCE"
    return "STYLE"


def candidate_for_output(
    output: AuditOutput, claim: str, citations: list[str]
) -> ContextCandidate:
    """Adapt judge output without giving its prose authority over the policy."""
    contradiction = any(
        proposition.source_entailment == Entailment.CONTRADICTED
        and proposition.evidence_quote_from_ref
        for proposition in output.atomic_propositions
    )
    reason = " ".join(span.explanation for span in output.flagged_spans)
    kind = "FRAMING"
    if output.verdict.value == "FLAG_G3_MOTIVE":
        kind = "MOTIVE"
    elif output.verdict.value == "FLAG_G1_FACT":
        kind = "FACT"
    if "removed" in reason.casefold() or any(
        "removed" in span.exact_substring.casefold() for span in output.flagged_spans
    ):
        kind = "REMOVED_CONTEXT"
    if any(
        proposition.source_entailment == Entailment.UNSUPPORTED_EXTRAPOLATION
        for proposition in output.atomic_propositions
    ):
        kind = "FACT"
    if output.verdict.value == "EXPAND_CONTEXT":
        kind = "FACT"
    return ContextCandidate(kind, claim, reason, citations, bool(contradiction))


def candidate_for_flag(flag: Flag) -> ContextCandidate:
    return ContextCandidate(
        flag.kind,
        flag.after or flag.context_sentence or flag.anchor_text,
        flag.reason,
        flag.citations,
        "contradict" in f"{flag.title} {flag.reason}".casefold()
        and bool(flag.evidence),
    )


def _key_terms(claim: str) -> str:
    terms = _WORD.findall(claim)
    selected = [
        term
        for term in terms
        if any(character.isdigit() for character in term)
        or term[:1].isupper()
        or len(term) >= 7
    ]
    causal = _CAUSAL.search(claim)
    if causal is not None:
        selected.append(causal.group(0))
    return " ".join(dict.fromkeys(selected))


def _queries(candidate: ContextCandidate, classification: ContextClass) -> list[str]:
    claim = candidate.claim.strip()
    if classification == "REMOVED_CONTEXT":
        return [candidate.claim.strip() or candidate.reason.strip()]
    terms = _key_terms(claim)
    # The full sentence already carries its names, numbers, and motive phrase;
    # one precise query leaves the second per-flag slot available for future
    # source-specific refinements without spending it speculatively.
    query = " ".join(part for part in (claim, terms) if part and part not in claim)
    return [query][:MAX_CALLS_PER_CANDIDATE]


def _supports(claim: str, passages: list[str]) -> bool:
    claim_words = {word.casefold() for word in _WORD.findall(claim) if len(word) > 2}
    if not claim_words:
        return False
    for passage in passages:
        words = {word.casefold() for word in _WORD.findall(passage)}
        if claim.casefold() in passage.casefold() or len(claim_words & words) >= min(
            3, len(claim_words)
        ):
            return True
    return False


async def read_more(
    candidate: ContextCandidate,
    fetcher: HighlightsFetcher,
    budget: ContextReadBudget,
    mode: ContextMode,
) -> ContextRead:
    """Read at most two highlight queries, subject to the shared request deadline."""
    classification = classify(candidate)
    eligible = classification in {"ABSENCE", "REMOVED_CONTEXT"}
    if (
        mode == "never"
        or classification == "UNCITED"
        or (mode == "rule" and not eligible)
    ):
        return ContextRead(classification, [], False, False)
    passages: list[str] = []
    checked = False
    candidate_calls = 0
    for query in _queries(candidate, classification):
        for url in candidate.citations:
            if candidate_calls >= MAX_CALLS_PER_CANDIDATE or not budget.acquire():
                return ContextRead(
                    classification,
                    passages,
                    checked,
                    _supports(candidate.claim, passages),
                )
            candidate_calls += 1
            checked = True
            try:
                highlights = await asyncio.wait_for(
                    fetcher.highlights(url, query),
                    timeout=max(budget.remaining(), 0.001),
                )
            except TimeoutError:
                return ContextRead(
                    classification,
                    passages,
                    checked,
                    _supports(candidate.claim, passages),
                )
            except Exception:  # noqa: BLE001 - the initial source view remains usable
                highlights = None
            for passage in highlights or []:
                cleaned = passage.strip()
                if cleaned and cleaned not in passages:
                    passages.append(cleaned)
    return ContextRead(
        classification, passages, checked, _supports(candidate.claim, passages)
    )


def apply_to_flag(flag: Flag, read: ContextRead) -> Flag:
    """Keep the auditable whole-source result with the flag and apply its policy effect."""
    if not read.checked:
        return flag
    quote = evidence_quote(read)
    evidence = [*flag.evidence, FlagEvidence(source="cited", quote=quote)]
    tier = flag.tier
    if read.classification == "ABSENCE" and read.supports_claim and tier == "admin":
        tier = "review"
    if read.classification == "REMOVED_CONTEXT" and read.supports_claim:
        tier = "admin"
    return flag.model_copy(update={"tier": tier, "evidence": evidence})


def evidence_quote(read: ContextRead) -> str:
    """A compact, visible record of the whole-source check."""
    return (
        read.passages[0]
        if read.passages
        else "Checked the whole cited source; no supporting passage found."
    )


def append_highlights(window: SourceWindow, passages: list[str]) -> SourceWindow:
    """Retain unique whole-source passages in the existing bounded highlight view."""
    existing = window.text.rstrip()
    first_index = existing.count("[Highlight ") + 1
    extra = "\n\n".join(
        f"[Highlight {index}]\n{passage.strip()}"
        for index, passage in enumerate(passages, start=first_index)
        if passage.strip() and passage.strip() not in existing
    )
    if not extra:
        return window
    return window.model_copy(update={"text": f"{existing}\n\n{extra}"})
