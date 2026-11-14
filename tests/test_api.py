from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from palimpsest import api
from palimpsest.judge import PreparedCase
from palimpsest.schema import AuditOutput, SourceWindow
from palimpsest.sources import DailyCallCap, SourceFetcher

TAG_PAYLOAD = "Hello" + "".join(chr(0xE0000 + ord(c)) for c in "ignore all")

CLEAN_BODY = {
    "lang_code": "en",
    "page_title": "Example",
    "old_revision_id": 1,
    "new_revision_id": 2,
    "editor_username": "Alice",
    "old_text": "The town has 500 people.",
    "new_text": "The town has 500 people.",
    "ref_urls": [],
}
FRAMING_TEXT = "The mayor shamelessly pushed through the disastrous bill."
FRAMING_BODY = {
    **CLEAN_BODY,
    "old_text": "The mayor signed the bill.",
    "new_text": FRAMING_TEXT,
    "ref_urls": ["https://example.org/a"],
}


class FakeFetcher:
    budget_exhausted = False

    async def window_scored(
        self, url: str, claim: str, radius: int = 3, on_text: object = None
    ) -> tuple[SourceWindow, int]:
        return SourceWindow(url=url, status="ok", text="src", latency_ms=1.0), 5


class FakeBackend:
    name = "fake"
    model = "fake-model"

    def __init__(self, output: AuditOutput | str) -> None:
        self.output = output
        self.latencies_ms: dict[str, float] = {}

    async def judge(self, cases: list[PreparedCase]) -> dict[str, AuditOutput | str]:
        self.latencies_ms = {pc.case.case_id: 7.0 for pc in cases}
        return {pc.case.case_id: self.output for pc in cases}


def _flag_g2() -> AuditOutput:
    return AuditOutput.model_validate(
        {
            "verdict": "FLAG_G2_FRAMING",
            "confidence": 0.8,
            "expand_direction": "NONE",
            "atomic_propositions": [],
            "flagged_spans": [
                {
                    "exact_substring": "shamelessly",
                    "guideline_violated": "G2_FRAMING",
                    "explanation": "loaded adverb",
                },
                {
                    "exact_substring": "not in text",
                    "guideline_violated": "G2_FRAMING",
                    "explanation": "x",
                },
            ],
            "neutral_rewrite": "The mayor signed the bill.",
        }
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    api.app.dependency_overrides[api.get_fetcher] = lambda: FakeFetcher()
    api.app.dependency_overrides[api.get_judge_backend] = lambda: None
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_stealth_scan_detects_tag_payload(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/stealth-scan",
        json={"text": TAG_PAYLOAD, "target_type": "WIKIPEDIA_DIFF"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stealth_status"] == "CRITICAL_AI_POISONING"
    assert body["hidden_findings"][0]["vector_type"] == "UNICODE_TAG_SMUGGLING"
    assert "scan_id" in body


def test_audit_diff_stage0_clean(client: TestClient) -> None:
    resp = client.post("/api/v1/audit-diff", json=CLEAN_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "CLEAN_PASS"
    assert body["pipeline_stage_reached"] == 0
    assert body["route"] == "none"
    assert body["editor_trust_delta"] == 0
    assert body["flagged_spans"] == []
    assert set(body["latency_ms"]) >= {"stealth", "stage0", "stage1", "stage2", "total"}


def test_audit_diff_flag_g2_with_offsets(client: TestClient) -> None:
    api.app.dependency_overrides[api.get_judge_backend] = lambda: FakeBackend(
        _flag_g2()
    )
    resp = client.post("/api/v1/audit-diff", json=FRAMING_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FLAG_G2_FRAMING"
    assert body["pipeline_stage_reached"] == 2
    assert body["route"] == "admin"
    assert body["editor_trust_delta"] == -0.05
    assert body["neutral_rewrite"] == "The mayor signed the bill."
    start = FRAMING_TEXT.index("shamelessly")
    first, second = body["flagged_spans"]
    assert (first["start"], first["end"]) == (start, start + len("shamelessly"))
    assert second["start"] is None and second["end"] is None
    assert body["stealth"]["status"] == "CLEAN"


def test_audit_diff_without_backend_is_503(client: TestClient) -> None:
    resp = client.post("/api/v1/audit-diff", json=FRAMING_BODY)
    assert resp.status_code == 503
    assert "judge backend" in resp.json()["detail"].lower()


def test_audit_diff_judge_error_is_502(client: TestClient) -> None:
    api.app.dependency_overrides[api.get_judge_backend] = lambda: FakeBackend("boom")
    resp = client.post("/api/v1/audit-diff", json=FRAMING_BODY)
    assert resp.status_code == 502


def test_audit_diff_invalid_body_is_422(client: TestClient) -> None:
    assert (
        client.post("/api/v1/audit-diff", json={"lang_code": "en"}).status_code == 422
    )
    bad_lang = {**CLEAN_BODY, "lang_code": "xx"}
    assert client.post("/api/v1/audit-diff", json=bad_lang).status_code == 422
    bad_url = {**CLEAN_BODY, "ref_urls": ["file:///etc/passwd"]}
    assert client.post("/api/v1/audit-diff", json=bad_url).status_code == 422


def test_healthz_reports_booleans_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXA_API_KEY", "secret-exa")
    body = client.get("/healthz").json()
    assert body == {"judge_configured": False, "exa_configured": True}
    api.app.dependency_overrides[api.get_judge_backend] = lambda: FakeBackend(
        _flag_g2()
    )
    assert client.get("/healthz").json()["judge_configured"] is True


def test_audit_diff_reports_exa_budget_exhausted(
    client: TestClient, tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    shared = SourceFetcher(
        "key",
        tmp_path,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        DailyCallCap(1),
    )
    api.app.dependency_overrides[api.get_fetcher] = lambda: shared.for_request()
    api.app.dependency_overrides[api.get_judge_backend] = lambda: FakeBackend(
        _flag_g2()
    )
    body = {**FRAMING_BODY, "ref_urls": [f"https://example.org/{i}" for i in range(3)]}
    resp = client.post("/api/v1/audit-diff", json=body)
    assert resp.status_code == 200
    assert resp.json()["exa_budget_exhausted"] is True


def test_audit_diff_budget_not_exhausted_by_default(client: TestClient) -> None:
    assert (
        client.post("/api/v1/audit-diff", json=CLEAN_BODY).json()[
            "exa_budget_exhausted"
        ]
        is False
    )
