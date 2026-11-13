import pytest
from pydantic import ValidationError

from palimpsest.schema import AuditOutput, Verdict

EXAMPLE = """{
  "verdict": "FLAG_G3_MOTIVE",
  "confidence": 0.87,
  "expand_direction": "NONE",
  "atomic_propositions": [
    {
      "clause_text": "The minister resigned to avoid an inquiry.",
      "clause_type": "MOTIVE_CAUSE",
      "source_entailment": "UNSUPPORTED_EXTRAPOLATION",
      "evidence_quote_from_ref": null
    }
  ],
  "flagged_spans": [
    {
      "exact_substring": "to avoid an inquiry",
      "guideline_violated": "G3_MOTIVE",
      "explanation": "Motive not attributed to the source."
    }
  ],
  "neutral_rewrite": "The minister resigned."
}"""


def test_audit_output_roundtrip() -> None:
    out = AuditOutput.model_validate_json(EXAMPLE)
    assert out.verdict == Verdict.FLAG_G3_MOTIVE
    assert len(out.atomic_propositions) == 1
    assert out.flagged_spans[0].exact_substring == "to avoid an inquiry"
    assert AuditOutput.model_validate_json(out.model_dump_json()) == out


def test_audit_output_rejects_unknown_verdict() -> None:
    bad = EXAMPLE.replace('FLAG_G3_MOTIVE"', 'MAYBE_BIASED"', 1)
    with pytest.raises(ValidationError):
        AuditOutput.model_validate_json(bad)
