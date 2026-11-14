"""Two-tier judge: a cheap first pass, and a stronger judge only for what it flags.

Offline on 266 real edits (session 2): same admin-queue precision as the strong
judge alone, 84% of its revert catches, at 20% of its calls.
"""

from palimpsest.judge import AsyncJudge, PreparedCase, judge_with_latencies
from palimpsest.schema import AuditOutput, Verdict

_FLAGS = (Verdict.FLAG_G1_FACT, Verdict.FLAG_G2_FRAMING, Verdict.FLAG_G3_MOTIVE)


def needs_second_opinion(result: AuditOutput | str) -> bool:
    """Escalate flags, and first-pass failures (never silently pass an error)."""
    return isinstance(result, str) or result.verdict in _FLAGS


class CascadeJudgeBackend:
    name = "cascade"

    def __init__(self, first: AsyncJudge, second: AsyncJudge) -> None:
        self.first = first
        self.second = second
        self.model = f"{first.model}->{second.model}"
        self.latencies_ms: dict[str, float] = {}
        self.decided_by: dict[str, str] = {}

    async def _run(
        self, cases: list[PreparedCase]
    ) -> tuple[dict[str, AuditOutput | str], dict[str, float], dict[str, str]]:
        """One cascade pass; all per-call state is local so concurrent calls cannot collide."""
        results, latencies = await judge_with_latencies(self.first, cases)
        escalate = [
            pc
            for pc in cases
            if needs_second_opinion(results.get(pc.case.case_id, "missing"))
        ]
        decided_by = {pc.case.case_id: self.first.model for pc in cases}
        latencies = {
            pc.case.case_id: latencies.get(pc.case.case_id, 0.0) for pc in cases
        }
        if escalate:
            second, second_latencies = await judge_with_latencies(self.second, escalate)
            for pc in escalate:
                case_id = pc.case.case_id
                results[case_id] = second.get(case_id, "no result from second judge")
                latencies[case_id] += second_latencies.get(case_id, 0.0)
                decided_by[case_id] = self.second.model
        return results, latencies, decided_by

    async def judge_timed(
        self, cases: list[PreparedCase]
    ) -> tuple[dict[str, AuditOutput | str], dict[str, float]]:
        results, latencies, _ = await self._run(cases)
        return results, latencies

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        results, latencies, decided_by = await self._run(cases)
        self.latencies_ms.update(latencies)
        self.decided_by.update(decided_by)
        return results
