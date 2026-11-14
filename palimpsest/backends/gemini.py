"""Direct Gemini API backends (google-genai 3.3.0) replacing the file exchange."""

import asyncio
import os
import time
from typing import Final, Protocol, TypeVar

from dotenv import load_dotenv
from google.genai import Client, errors, types
from pydantic import BaseModel, ValidationError

from palimpsest.guided import GuidedAnswers, guided_to_audit
from palimpsest.judge import (
    PROMPT_VERSION,
    PROMPTS_DIR,
    PreparedCase,
    render_case_payload,
)
from palimpsest.reviewer import (
    REVIEWER_SYSTEM,
    ReviewerAnswers,
    ReviewerCandidate,
    render_reviewer_payload,
)
from palimpsest.schema import AuditOutput
from palimpsest.stealth.models import HiddenFinding
from palimpsest.stealth.triage import (
    TRIAGE_PROMPT_PATH,
    TriageVerdict,
    render_triage_batch,
)

DEFAULT_JUDGE_MODEL: Final = "gemini-4-hydrogen"
DEFAULT_REVIEWER_MODEL: Final = "gemini-4-argon"
# g03: LOW and HIGH gave identical flag decisions on 124 edits; LOW is 2.4x cheaper in thinking tokens and p95 latency.
DEFAULT_JUDGE_THINKING: Final = "LOW"
# TODO: the Decisions API may expose its own endpoint/SDK surface. Until that is
# documented and verified, triage goes through the same generate_content path.
DEFAULT_TRIAGE_MODEL: Final = "gemini-decision-1"
DEFAULT_CONCURRENCY: Final = 8
DEFAULT_TIMEOUT_SECONDS: Final = 60.0
DEFAULT_SEED: Final = 7
DEFAULT_BACKOFF_SECONDS: Final = 2.0
RETRYABLE_STATUS: Final = 429
TRIAGE_DIRECT_SUFFIX: Final = (
    "\n\nDIRECT API MODE: ignore any instruction about writing files or replying "
    "DONE. Classify the single item and return only its JSON object."
)

T = TypeVar("T", bound=BaseModel)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class _Models(Protocol):
    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse: ...


class _Aio(Protocol):
    @property
    def models(self) -> _Models: ...


class GeminiClient(Protocol):
    @property
    def aio(self) -> _Aio: ...


GEMINI_OPT_IN_ENV = "PALIMPSEST_USE_GEMINI"


def gemini_enabled() -> bool:
    """True only when the key is set AND the user opted in (PALIMPSEST_USE_GEMINI=1)."""
    load_dotenv()
    return bool(os.environ.get("GEMINI_API_KEY")) and (
        os.environ.get(GEMINI_OPT_IN_ENV) == "1"
    )


def load_gemini_api_key() -> str:
    """Read GEMINI_API_KEY from .env / environment; exit with a clear message if absent."""
    load_dotenv()
    if os.environ.get(GEMINI_OPT_IN_ENV) != "1":
        raise SystemExit(
            f"Gemini is disabled: set {GEMINI_OPT_IN_ENV}=1 to use GEMINI_API_KEY"
        )
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY is not set (put it in .env or the environment)"
        )
    return key


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def _thinking_config() -> types.ThinkingConfig | None:
    """GEMINI_THINKING_LEVEL (ThinkingConfig.thinking_level); unset means SDK default."""
    level = os.environ.get("GEMINI_THINKING_LEVEL", "").strip().upper()
    if not level:
        return None
    try:
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel(level))
    except ValueError:
        valid = ", ".join(t.value for t in types.ThinkingLevel)
        raise SystemExit(
            f"invalid GEMINI_THINKING_LEVEL {level!r}; use one of: {valid}"
        )


class _GeminiCaller:
    def __init__(
        self,
        model: str,
        client: GeminiClient | None,
        backoff_seconds: float,
    ) -> None:
        self.model = model
        self.client: GeminiClient = (
            client if client is not None else Client(api_key=load_gemini_api_key())
        )
        self.backoff_seconds = backoff_seconds
        self.timeout = _env_number("GEMINI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        self.semaphore = asyncio.Semaphore(
            int(_env_number("GEMINI_CONCURRENCY", DEFAULT_CONCURRENCY))
        )
        self.thinking = _thinking_config()
        # Running token totals for cost reporting; counters only, no per-call state.
        self.usage: dict[str, int] = {
            "calls": 0,
            "input": 0,
            "output": 0,
            "thinking": 0,
        }

    def _record_usage(self, response: types.GenerateContentResponse) -> None:
        meta = getattr(response, "usage_metadata", None)  # test doubles may omit it
        self.usage["calls"] += 1
        if meta is None:
            return
        self.usage["input"] += meta.prompt_token_count or 0
        self.usage["output"] += meta.candidates_token_count or 0
        self.usage["thinking"] += meta.thoughts_token_count or 0

    async def _call(
        self, system: str, contents: str, schema: type[BaseModel]
    ) -> str | None:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
            # Fixed seed: repeated audits of the same edit should give the same flags.
            seed=_env_int("GEMINI_SEED", DEFAULT_SEED),
            thinking_config=self.thinking,
        )
        response = await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            ),
            timeout=self.timeout,
        )
        self._record_usage(response)
        return response.text

    async def generate(
        self, system: str, contents: str, schema: type[T]
    ) -> tuple[T | str, float]:
        """Validated model output or an error string, plus ms spent on the call itself."""
        async with self.semaphore:
            # Timed inside the semaphore so queueing behind other calls is not counted.
            started = time.perf_counter()
            text: str | None = None
            error: str | None = None
            for attempt in range(2):
                try:
                    text = await self._call(system, contents, schema)
                    error = None
                    break
                except errors.APIError as exc:
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    retryable = exc.code == RETRYABLE_STATUS or exc.code >= 500
                    if attempt == 0 and retryable:
                        await asyncio.sleep(self.backoff_seconds)
                        continue
                    break
                except TimeoutError:
                    error = f"TimeoutError: no response within {self.timeout}s"
                    break
                except Exception as exc:  # noqa: BLE001 - SDK/transport failures must not abort a run
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    break
        elapsed_ms = (time.perf_counter() - started) * 1000
        if error is not None:
            return error, elapsed_ms
        if not text:
            return "EmptyResponse: model returned no text", elapsed_ms
        try:
            return schema.model_validate_json(text), elapsed_ms
        except ValidationError as exc:
            return f"{type(exc).__name__}: {str(exc)[:200]}", elapsed_ms


class GeminiJudgeBackend:
    name = "gemini"

    def __init__(
        self,
        client: GeminiClient | None = None,
        prompt_version: str = PROMPT_VERSION,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        model: str | None = None,
    ) -> None:
        self.model = (
            model or os.environ.get("GEMINI_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
        )
        self._caller = _GeminiCaller(self.model, client, backoff_seconds)
        if self._caller.thinking is None:
            # The judge pins its own default instead of the SDK's; GEMINI_THINKING_LEVEL still overrides.
            self._caller.thinking = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(DEFAULT_JUDGE_THINKING)
            )
        self._system = (PROMPTS_DIR / f"{prompt_version}.txt").read_text()
        self.prompt_version = prompt_version
        self.latencies_ms: dict[str, float] = {}

    @property
    def usage(self) -> dict[str, int]:
        return self._caller.usage

    async def judge_timed(
        self, cases: list[PreparedCase]
    ) -> tuple[dict[str, AuditOutput | str], dict[str, float]]:
        """Results plus latencies, with no per-call state kept on the instance."""

        async def one(pc: PreparedCase) -> tuple[str, AuditOutput | str, float]:
            # Payload normalisation is CPU-bound and can be large for a full
            # revision.  Keep it off the loop so concurrent best-effort checks
            # (such as rendered citation dates) can start their I/O promptly.
            contents = await asyncio.to_thread(render_case_payload, pc)
            result: AuditOutput | str
            if self.prompt_version == "stage2_v9":
                guided_result, ms = await self._caller.generate(
                    self._system, contents, GuidedAnswers
                )
                if isinstance(guided_result, GuidedAnswers):
                    result = guided_to_audit(
                        guided_result,
                        pc.case.old_text,
                        pc.case.new_text,
                        pc.window.text if pc.window is not None else "",
                    )
                else:
                    result = guided_result
            else:
                result, ms = await self._caller.generate(
                    self._system, contents, AuditOutput
                )
            return pc.case.case_id, result, ms

        rows = await asyncio.gather(*(one(pc) for pc in cases))
        return {cid: r for cid, r, _ in rows}, {cid: ms for cid, _, ms in rows}

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        results, latencies = await self.judge_timed(cases)
        self.latencies_ms.update(latencies)
        return results


class GeminiReviewerBackend:
    """One edit-level, low-thinking Argon second opinion."""

    name = "gemini_reviewer"

    def __init__(
        self,
        client: GeminiClient | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.model = os.environ.get("GEMINI_REVIEWER_MODEL") or DEFAULT_REVIEWER_MODEL
        self._caller = _GeminiCaller(self.model, client, backoff_seconds)
        # Reviewer latency is a hard product budget, independent of judge settings.
        self._caller.timeout = 12.0
        self._caller.thinking = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.LOW
        )

    @property
    def usage(self) -> dict[str, int]:
        return self._caller.usage

    async def review(
        self, page_title: str, language: str, candidates: list[ReviewerCandidate]
    ) -> tuple[ReviewerAnswers | str, float]:
        payload = await asyncio.to_thread(
            render_reviewer_payload, page_title, language, candidates
        )
        return await self._caller.generate(REVIEWER_SYSTEM, payload, ReviewerAnswers)


class GeminiTriageBackend:
    name = "gemini"

    def __init__(
        self,
        client: GeminiClient | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.model = os.environ.get("GEMINI_TRIAGE_MODEL") or DEFAULT_TRIAGE_MODEL
        self._caller = _GeminiCaller(self.model, client, backoff_seconds)
        self.latencies_ms: dict[str, float] = {}

    async def triage(
        self, items: list[tuple[str, HiddenFinding]]
    ) -> dict[str, TriageVerdict | str]:
        async def one(
            item: tuple[str, HiddenFinding],
        ) -> tuple[str, TriageVerdict | str]:
            finding_id = item[0]
            system = (
                TRIAGE_PROMPT_PATH.read_text(encoding="utf-8").replace(
                    "{RESULTS_PATH}", "(unused)"
                )
                + TRIAGE_DIRECT_SUFFIX
            )
            contents = render_triage_batch([item], TRIAGE_PROMPT_PATH).split(
                "========== ITEMS ==========", 1
            )[-1]
            result, ms = await self._caller.generate(system, contents, TriageVerdict)
            self.latencies_ms[finding_id] = ms
            return finding_id, result

        return dict(await asyncio.gather(*(one(i) for i in items)))
