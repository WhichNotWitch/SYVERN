import pytest

from syvern.adapters.stub import extract_element_summary
from syvern.settings import SyvernSettings
from syvern.structural import match_structural, parse_reference


REFERENCE = {
    "elements": [
        {"type": "part", "qualified_name": "vehicle.engine"},
        {"type": "attribute", "qualified_name": "vehicle.mass"},
    ],
    "requirements": ["req.power", "req.mass"],
    "coverage": {
        "req.power": ["vehicle.engine"],
        "req.mass": ["vehicle.mass"],
    },
}


class FakeSoftMatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def match(self, generated, reference) -> bool:
        self.calls.append((generated.qualified_name, reference.qualified_name))
        return generated.qualified_name == "vehicle.motor" and reference.qualified_name == "vehicle.engine"


def test_parse_reference_normalizes_elements_requirements_and_coverage():
    reference = parse_reference({
        "elements": [{"type": " Part ", "qualified_name": " Vehicle.Engine "}],
        "requirements": [" Req.Power "],
        "coverage": {" Req.Power ": [" Vehicle.Engine "]},
    })

    assert [item.model_dump() for item in reference.elements] == [
        {"type": "part", "qualified_name": "vehicle.engine"}
    ]
    assert reference.requirements == ["req.power"]
    assert reference.coverage == {"req.power": {"vehicle.engine"}}


def test_parse_reference_ignores_malformed_entries():
    reference = parse_reference({
        "elements": [
            {"type": "part", "qualified_name": "vehicle.engine"},
            {"type": "", "qualified_name": "broken"},
            "not-an-element",
        ],
        "requirements": "not-a-list",
        "coverage": ["not-a-dict"],
    })

    assert [item.model_dump() for item in reference.elements] == [
        {"type": "part", "qualified_name": "vehicle.engine"}
    ]
    assert reference.requirements == []
    assert reference.coverage == {}


def test_exact_match_scores_all_structural_metrics():
    summary = match_structural(
        extract_element_summary("part vehicle.engine attribute vehicle.mass"),
        REFERENCE,
        SyvernSettings(),
    )

    assert summary.evaluated is True
    assert summary.precision == 1.0
    assert summary.recall == 1.0
    assert summary.f1 == 1.0
    assert summary.requirement_coverage == 1.0
    assert summary.hallucinated_elements == 0
    assert summary.ged_accuracy == 1.0
    assert summary.matching_policy_id == "h9-normalized-fuzzy-v1"
    assert summary.exact_matched == 2
    assert summary.normalized_matched == 0
    assert summary.fuzzy_matched == 0
    assert summary.soft_matched == 0


def test_missing_generated_elements_reduce_recall_and_f1():
    summary = match_structural(
        generated=extract_element_summary("part vehicle.engine"),
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert summary.precision == 1.0
    assert summary.recall == 0.5
    assert summary.f1 == pytest.approx(2 / 3)
    assert summary.requirement_coverage == 0.5
    assert summary.hallucinated_elements == 0
    assert summary.ged_accuracy == 0.5


def test_extra_generated_elements_reduce_precision_and_count_hallucinations():
    summary = match_structural(
        generated=extract_element_summary("part vehicle.engine attribute vehicle.mass part vehicle.wing"),
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert summary.precision == pytest.approx(2 / 3)
    assert summary.recall == 1.0
    assert summary.f1 == pytest.approx(0.8)
    assert summary.requirement_coverage == 1.0
    assert summary.hallucinated_elements == 1
    assert summary.ged_accuracy == pytest.approx(2 / 3)


def test_duplicate_elements_use_multiset_semantics():
    reference = {
        "elements": [
            {"type": "part", "qualified_name": "wheel"},
            {"type": "part", "qualified_name": "wheel"},
        ],
    }
    summary = match_structural(
        generated=extract_element_summary("part wheel"),
        reference=reference,
        settings=SyvernSettings(),
    )

    assert summary.precision == 1.0
    assert summary.recall == 0.5
    assert summary.f1 == pytest.approx(2 / 3)


def test_normalized_match_uses_leaf_names_and_ignores_generated_suffixes():
    summary = match_structural(
        generated=extract_element_summary("part engine_1 attribute mass-generated"),
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert summary.precision == 1.0
    assert summary.recall == 1.0
    assert summary.f1 == 1.0
    assert summary.requirement_coverage == 1.0
    assert summary.hallucinated_elements == 0
    assert summary.exact_matched == 0
    assert summary.normalized_matched == 2
    assert summary.fuzzy_matched == 0


def test_fuzzy_match_applies_within_same_type_after_exact_and_normalized_passes():
    summary = match_structural(
        generated=extract_element_summary("part vehicle.engin attribute vehicle.mass part vehicle.wheel"),
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert summary.precision == pytest.approx(2 / 3)
    assert summary.recall == 1.0
    assert summary.f1 == pytest.approx(0.8)
    assert summary.hallucinated_elements == 1
    assert summary.exact_matched == 1
    assert summary.normalized_matched == 0
    assert summary.fuzzy_matched == 1


def test_fuzzy_match_does_not_cross_element_types():
    summary = match_structural(
        generated=extract_element_summary("attribute vehicle.engin"),
        reference={"elements": [{"type": "part", "qualified_name": "vehicle.engine"}]},
        settings=SyvernSettings(),
    )

    assert summary.precision == 0.0
    assert summary.recall == 0.0
    assert summary.fuzzy_matched == 0
    assert summary.hallucinated_elements == 1
    assert summary.ged_accuracy == 0.0


def test_soft_matcher_can_match_remaining_same_type_elements_after_deterministic_passes():
    matcher = FakeSoftMatcher()

    summary = match_structural(
        generated=extract_element_summary("part vehicle.motor attribute vehicle.mass"),
        reference=REFERENCE,
        settings=SyvernSettings(),
        soft_matcher=matcher,
    )

    assert summary.precision == 1.0
    assert summary.recall == 1.0
    assert summary.f1 == 1.0
    assert summary.requirement_coverage == 1.0
    assert summary.hallucinated_elements == 0
    assert summary.exact_matched == 1
    assert summary.soft_matched == 1
    assert matcher.calls == [("vehicle.motor", "vehicle.engine")]


def test_ged_accuracy_counts_same_size_unmatched_pairs_as_substitutions():
    summary = match_structural(
        generated=extract_element_summary("part vehicle.engine attribute vehicle.length"),
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert summary.precision == 0.5
    assert summary.recall == 0.5
    assert summary.ged_accuracy == 0.5


def test_empty_reference_evaluates_to_zero_scores():
    summary = match_structural(
        generated=extract_element_summary("part vehicle.engine"),
        reference={},
        settings=SyvernSettings(),
    )

    assert summary.evaluated is True
    assert summary.precision == 0.0
    assert summary.recall == 0.0
    assert summary.f1 == 0.0
    assert summary.requirement_coverage == 0.0
    assert summary.hallucinated_elements == 1
    assert summary.ged_accuracy == 0.0
