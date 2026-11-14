import asyncio

import httpx

from palimpsest.value_check import (
    ValueCheck,
    _wikidata_check,
    check_values,
    evidence_outcome,
    suppress_supported_value_reviews,
    value_check_flags,
    value_matches,
)


def test_value_matching_normalises_dates_numbers_and_names() -> None:
    assert value_matches("5. kesäkuuta 1960", "5 June 1960")
    assert value_matches("5 juni 1960", "1960-06-05")
    assert value_matches("1,234.50", "1 234,50 people")
    assert value_matches("Mäki", "maki was present")
    assert value_matches("1960", "on 5.6.1960")


def test_exa_outcome_logic() -> None:
    assert (
        evidence_outcome("1960", "1961", ["The event was in 1960."]) == "SUPPORTS_OLD"
    )
    assert (
        evidence_outcome("1960", "1961", ["The event was in 1961."]) == "SUPPORTS_NEW"
    )
    assert evidence_outcome("1960", "1961", ["1960 was revised to 1961."]) == "BOTH"
    assert evidence_outcome("1960", "1961", ["The event happened later."]) == "NEITHER"


def test_wikidata_time_quantity_and_item_matching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "titles" in request.url.params:
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q1": {
                            "claims": {
                                "P569": [
                                    {
                                        "mainsnak": {
                                            "datavalue": {
                                                "value": {
                                                    "time": "+1960-06-05T00:00:00Z",
                                                    "precision": 11,
                                                }
                                            }
                                        }
                                    }
                                ],
                                "P1082": [
                                    {
                                        "mainsnak": {
                                            "datavalue": {"value": {"amount": "+1234"}}
                                        }
                                    }
                                ],
                                "P19": [
                                    {"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}
                                ],
                            }
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={"entities": {"Q2": {"labels": {"en": {"value": "Helsinki"}}}}},
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            time = await _wikidata_check(client, "en", "Example", "1960", "1961")
            quantity = await _wikidata_check(client, "en", "Example", "1,234", "1,235")
            item = await _wikidata_check(client, "en", "Example", "Helsinki", "Turku")
        assert (time.outcome, time.property_id) == ("SUPPORTS_OLD", "P569")
        assert quantity.outcome == "SUPPORTS_OLD"
        assert item.outcome == "SUPPORTS_OLD"

    asyncio.run(run())


def test_wikidata_full_date_requires_day_precision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q1": {
                        "claims": {
                            "P569": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "value": {
                                                "time": "+1960-00-00T00:00:00Z",
                                                "precision": 9,
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await _wikidata_check(
                client, "en", "Example", "5 June 1960", "6 June 1960"
            )
        assert result.outcome == "NEITHER"

    asyncio.run(run())


def test_deadline_and_failure_are_isolated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(500)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await check_values(
                lang="en",
                title="Example",
                old_text="Population 1997.",
                new_text="Population 2009.",
                ref_urls=None,
                client=client,
                deadline_s=0.001,
            )
        assert [check.outcome for check in report.checks] == ["NEITHER"]

    asyncio.run(run())


def test_flag_mapping_only_escalates_old_evidence() -> None:
    checks = [
        ValueCheck(
            old_value="1997",
            new_value="2009",
            outcome="SUPPORTS_OLD",
            source="wikidata",
            evidence="1997",
            property_id="P1082",
        ),
        ValueCheck(
            old_value="A", new_value="B", outcome="SUPPORTS_NEW", source="cited"
        ),
    ]
    flags = value_check_flags(checks, "Population 2009.")
    assert len(flags) == 1
    assert flags[0].tier == "admin"
    assert (
        flags[0].reason == "The edit changes 1997 to 2009; Wikidata (P1082) gives 1997."
    )


def test_new_evidence_suppresses_only_legacy_value_review() -> None:
    flagged = value_check_flags(
        [
            ValueCheck(
                old_value="1997",
                new_value="2009",
                outcome="SUPPORTS_OLD",
                source="cited",
            )
        ],
        "2009",
    )[0].model_copy(update={"check": "judge", "reason": "VALUE_CHANGED: review"})
    retained = flagged.model_copy(update={"reason": "Another factual concern"})
    checks = [
        ValueCheck(
            old_value="1997", new_value="2009", outcome="SUPPORTS_NEW", source="cited"
        )
    ]
    assert suppress_supported_value_reviews([flagged, retained], checks) == [retained]
