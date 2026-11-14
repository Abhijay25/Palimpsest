"""Two-tier judge: a cheap first pass, and a stronger judge only for what it flags.

Offline on 266 real edits (session 2): same admin-queue precision as the strong
judge alone, 84% of its revert catches, at 20% of its calls.
"""

from palimpsest.judge import AsyncJudge, PreparedCase
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

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        results = await self.first.judge(cases)
        escalate = [
            pc
            for pc in cases
            if needs_second_opinion(results.get(pc.case.case_id, "missing"))
        ]
        for pc in cases:
            case_id = pc.case.case_id
            self.latencies_ms[case_id] = self.first.latencies_ms.get(case_id, 0.0)
            self.decided_by[case_id] = self.first.model
        if escalate:
            second = await self.second.judge(escalate)
            for pc in escalate:
                case_id = pc.case.case_id
                results[case_id] = second.get(case_id, "no result from second judge")
                self.latencies_ms[case_id] += self.second.latencies_ms.get(case_id, 0.0)
                self.decided_by[case_id] = self.second.model
        return results
