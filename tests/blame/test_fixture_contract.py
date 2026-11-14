"""Integrity checks for independently authored Palimpsest Blame ground truth."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import unittest


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(fixture_id: str) -> dict:
    path = FIXTURES / f"{fixture_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def utf16_slice(text: str, start: int, end: int) -> str:
    data = text.encode("utf-16-le")
    return data[start * 2:end * 2].decode("utf-16-le")


def alias_values(value: object, aliases: set[str]) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(alias_values(child, aliases) for child in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(alias_values(child, aliases) for child in value)) if value else set()
    return {value} if isinstance(value, str) and value in aliases else set()


class FixtureContractTests(unittest.TestCase):
    def test_all_documents_are_versioned_and_have_unique_ids(self) -> None:
        docs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))]
        self.assertGreaterEqual(len(docs), 6)
        self.assertTrue(all(doc.get("schema_version") == 1 for doc in docs))
        self.assertEqual(len({doc["id"] for doc in docs}), len(docs))
        self.assertTrue({"synthetic_history", "parser_cases", "outcome_controls"}.issubset({d["kind"] for d in docs}))

    def test_history_aliases_and_expected_revision_references_are_closed(self) -> None:
        for path in sorted(FIXTURES.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("kind") != "synthetic_history":
                continue
            aliases = [revision["alias"] for revision in doc["revisions"]]
            self.assertTrue(aliases)
            self.assertEqual(aliases, [f"r{i}" for i in range(1, len(aliases) + 1)], path.name)
            self.assertEqual(len(aliases), len(set(aliases)), path.name)
            self.assertEqual(sorted(doc["revisions"], key=lambda r: utc(r["timestamp"])), doc["revisions"], path.name)
            self.assertEqual(doc["expected"]["snapshot"], aliases[-1], path.name)
            refs = alias_values(doc["expected"], set(aliases))
            self.assertTrue(refs.issubset(set(aliases)), path.name)

    def test_cross_contributor_selection_has_explicit_ground_truth(self) -> None:
        doc = load_fixture("cross_contributor_deletion")
        revisions = {revision["alias"]: revision["text"] for revision in doc["revisions"]}
        expected = doc["expected"]
        selection = expected["selection"]
        self.assertIn(selection["text"], revisions[expected["snapshot"]])
        self.assertEqual(utf16_slice(revisions[expected["snapshot"]], selection["start"], selection["end"]), selection["text"])
        segments = expected["last_change_segments"]
        self.assertEqual(" ".join(segment["text"] for segment in segments), selection["text"])
        self.assertEqual({"r1", "r2", "r4"}, {segment["revision"] for segment in segments})
        for event in expected["events"]:
            before = revisions[f"r{int(event['revision'][1:]) - 1}"]
            after = revisions[event["revision"]]
            self.assertIn(event["before"], before)
            if event["after"]:
                self.assertIn(event["after"], after)
            else:
                self.assertNotIn(event["before"].strip(), after)
            if "before_range" in event:
                self.assertEqual(utf16_slice(before, *event["before_range"]), event["before"], event)
                if event["after_range"] is None:
                    self.assertEqual(event["after"], "", event)
                else:
                    self.assertEqual(utf16_slice(after, *event["after_range"]), event["after"], event)
        untouched = expected["untouched_text"]
        self.assertTrue(all(untouched["text"] in text for text in revisions.values()))
        self.assertEqual(untouched["last_change"], "r1")

    def test_repeated_move_and_revert_demand_ambiguity(self) -> None:
        doc = load_fixture("repeated_move_revert")
        expected = doc["expected"]
        final = doc["revisions"][-1]["text"]
        self.assertEqual(final.count(expected["selection"]["text"]), 2)
        self.assertTrue(expected["ambiguity"]["required"])
        self.assertTrue(expected["ambiguity"]["must_not_claim_unique_original_author"])
        revisions = {revision["alias"]: revision["text"] for revision in doc["revisions"]}
        for event in expected["events"]:
            parent = f"r{int(event['revision'][1:]) - 1}"
            self.assertEqual(utf16_slice(revisions[parent], *event["before_range"]), event["before"])
            self.assertEqual(utf16_slice(revisions[event["revision"]], *event["after_range"]), event["after"])
        self.assertTrue(all(not event["ambiguous"] for event in expected["events"]))
        page_events = {(event["revision"], event["before"], event["after"]) for event in expected["events"]}
        selection_events = {(event["revision"], event["before"], event["after"]) for event in expected["selection"]["events"]}
        self.assertTrue(selection_events.issubset(page_events))
        self.assertEqual(selection_events, {("r2", "rests", "waits"), ("r3", "waits", "rests")})

    def test_chained_replacements_keep_selected_lineage_and_filter_unrelated_later_edit(self) -> None:
        doc = load_fixture("chained_replacements")
        revisions = doc["revisions"]
        expected = doc["expected"]
        self.assertEqual([revision["text"].split()[4] for revision in revisions[:3]], ["quick", "slow", "fast"])
        self.assertEqual(utf16_slice(revisions[-1]["text"], expected["selection"]["start"], expected["selection"]["end"]), "the fast mark")
        self.assertEqual([event["before"] for event in expected["events"][:2]], ["quick", "slow"])
        self.assertEqual([event["after"] for event in expected["events"][:2]], ["slow", "fast"])
        self.assertEqual(expected["events"][2]["before"], "old ")
        self.assertEqual(utf16_slice(revisions[2]["text"], *expected["events"][2]["before_range"]), "old ")
        self.assertEqual(expected["excluded_from_selection_timeline"], ["r5"])
        self.assertIn("calm", revisions[-1]["text"])
        self.assertEqual(expected["lineage_id_shape"], "local_revision_id:zero_based_token_index")

    def test_large_sparse_history_exceeds_500_tokens_and_has_independent_anchors(self) -> None:
        doc = load_fixture("large_unique_anchor_history")
        texts = [revision["text"].split() for revision in doc["revisions"]]
        self.assertEqual([len(tokens) for tokens in texts], [640, 640, 640])
        self.assertEqual(len(set(texts[0])), 640)
        self.assertEqual(doc["expected"]["token_count"], 640)
        self.assertEqual(texts[1][320], "swap0320")
        self.assertEqual(texts[2][600], "swap0600")
        self.assertEqual(texts[2][0], texts[0][0])
        self.assertEqual(texts[2][-1], texts[0][-1])
        final = doc["revisions"][-1]["text"]
        for segment in doc["expected"]["last_change_segments"]:
            self.assertEqual(utf16_slice(final, segment["start"], segment["end"]), segment["text"])

    def test_utf16_selection_range_includes_combining_mark_and_surrogate_pair(self) -> None:
        doc = load_fixture("unicode_utf16_selection")
        expected = doc["expected"]
        final = doc["revisions"][-1]["text"]
        selection = expected["selection"]
        self.assertEqual(utf16_slice(final, selection["start"], selection["end"]), selection["text"])
        self.assertEqual(selection["text"], "q\u0301 \U0001f603")
        self.assertIn("\u0301", selection["text"])
        self.assertTrue(all(value not in final for value in expected["must_not_normalize_to"]))
        self.assertEqual(len("\U0001f603".encode("utf-16-le")) // 2, 2)
        for part in expected["last_change_segments"]:
            self.assertIn(part["text"], final)

    def test_date_expectations_match_utc_inclusivity_and_tie_order(self) -> None:
        doc = load_fixture("date_boundaries")
        revisions = doc["revisions"]
        expected = doc["expected"]
        ordered = sorted(enumerate(revisions), key=lambda pair: (utc(pair[1]["timestamp"]), pair[0]), reverse=True)
        self.assertEqual([row["alias"] for _, row in ordered if utc(row["timestamp"]) == utc(revisions[-1]["timestamp"])], ["r3"])
        tie_order = [row["alias"] for _, row in ordered if utc(row["timestamp"]) == utc(revisions[0]["timestamp"])]
        self.assertEqual(tie_order, expected["same_second_order"])
        for query in expected["queries"]:
            bound = utc(query.get("bound", query.get("from", "1970-01-01T00:00:00Z")))
            if query["mode"] == "asof":
                eligible = [(i, r) for i, r in enumerate(revisions) if utc(r["timestamp"]) <= bound]
                selected = max(eligible, key=lambda pair: (utc(pair[1]["timestamp"]), pair[0]))[1]["alias"] if eligible else None
                self.assertEqual(selected, query["selected"])
            elif query["mode"] == "before":
                eligible = [(i, r) for i, r in enumerate(revisions) if utc(r["timestamp"]) < bound]
                selected = max(eligible, key=lambda pair: (utc(pair[1]["timestamp"]), pair[0]))[1]["alias"] if eligible else None
                self.assertEqual(selected, query["selected"])
            elif query["mode"] == "range":
                lo, hi = utc(query["from"]), utc(query["to"])
                matched = [r["alias"] for r in reversed(revisions) if lo <= utc(r["timestamp"]) <= hi]
                self.assertEqual(matched, query["versions"])

    def test_date_language_cases_are_valid_calendar_bounds_or_explicit_negatives(self) -> None:
        doc = load_fixture("date_language")
        self.assertEqual(doc["timezone"], "UTC")
        for case in doc["cases"]:
            if case["valid"]:
                for field, value in case.items():
                    if field.endswith("_utc"):
                        self.assertIsNotNone(utc(value))
                self.assertIn(case["mode"], {"asof", "before", "range"})
            else:
                self.assertIn(case["reason"], {"invalid_calendar_date", "reversed_range", "unsupported_language", "unsupported_or_ambiguous_pattern"})
        self.assertEqual(doc["manual_bounds"][0]["reason"], "invalid_utc_time")
        self.assertEqual(doc["manual_bounds"][1]["reason"], "reversed_range")
        self.assertEqual(doc["api_invalid_modes"][0]["reason"], "unsupported_mode")

    def test_unavailable_controls_never_expect_fabricated_authoritative_data(self) -> None:
        doc = load_fixture("honest_unavailable")
        controls = {row["id"]: row for row in doc["controls"]}
        self.assertGreaterEqual(len(controls), 6)
        self.assertTrue(controls["missing_import_mapping"]["must_not_infer_from_numeric_ids"])
        self.assertTrue(controls["suppressed_revision"]["must_not_leak_content_identity_or_cached_fields"])
        self.assertTrue(controls["generated_template_text"]["must_not_return_authoritative_spans"])

    def test_rendered_dom_cases_distinguish_markup_gaps_from_unmapped_text(self) -> None:
        mapped = load_fixture("rendered_mapped_selection")
        self.assertEqual(mapped["visible_text"][mapped["visible_text"].index(mapped["selection_text"]):][:len(mapped["selection_text"])], mapped["selection_text"])
        self.assertTrue(mapped["must_not_report_unmapped_visible_text"])
        self.assertIn("[[LINK_TARGET|existing article]]", mapped["wikitext"])
        self.assertIn("<ref", mapped["wikitext"])
        self.assertIn(mapped["citation_text"], mapped["wikitext"])
        generated = load_fixture("generated_unmapped_selection")
        self.assertIn("{{template_title}}", generated["wikitext_template"])
        self.assertIn(generated["generated_text"], generated["selection_text_template"])
        self.assertEqual(generated["expected_coverage"], "partial_or_unavailable")
        self.assertTrue(generated["must_not_authoritatively_attribute_generated_text"])

    def test_fragment_and_paragraph_cases_preserve_the_whole_user_quote(self) -> None:
        fragmented = load_fixture("fragmented_selection")
        self.assertEqual(len(fragmented["tokens"]), fragmented["fragment_count"])
        self.assertGreater(fragmented["fragment_count"], 64)
        self.assertEqual(len(set(fragmented["tokens"])), fragmented["fragment_count"])
        paragraph = load_fixture("paragraph_boundary_selection")
        self.assertIn("\n\n", paragraph["wikitext"])
        self.assertTrue(paragraph["must_retain_exact_selection"])


if __name__ == "__main__":
    unittest.main()
