import pytest

from syvern.intent import evaluate_intent
from syvern.settings import SyvernSettings


def test_matching_intent_reference_returns_evaluated_score():
    result = evaluate_intent(
        "part vehicle.engine attribute vehicle.mass",
        {
            "requirements": ["model engine"],
            "must_include": ["vehicle.engine", "vehicle.mass"],
            "must_not_include": ["aircraft.wing"],
        },
        SyvernSettings(),
    )

    assert result.evaluated is True
    assert result.source == "heuristic"
    assert result.score is not None
    assert result.score > 3.0


def test_forbidden_content_lowers_score():
    settings = SyvernSettings()
    intent_reference = {
        "must_include": ["vehicle.engine", "vehicle.mass"],
        "must_not_include": ["aircraft.wing"],
    }

    clean = evaluate_intent("part vehicle.engine attribute vehicle.mass", intent_reference, settings)
    forbidden = evaluate_intent(
        "part vehicle.engine attribute vehicle.mass part aircraft.wing",
        intent_reference,
        settings,
    )

    assert clean.score is not None
    assert forbidden.score is not None
    assert forbidden.score < clean.score


def test_empty_intent_reference_is_unevaluated():
    result = evaluate_intent("part vehicle.engine", {}, SyvernSettings())

    assert result.evaluated is False
    assert result.score is None
    assert result.source is None


def test_reference_with_no_evaluable_items_is_unevaluated():
    result = evaluate_intent("part vehicle.engine", {"notes": ["human only"]}, SyvernSettings())

    assert result.evaluated is False
    assert result.score is None
    assert result.source is None


def test_blank_text_is_unevaluated_even_with_reference():
    settings = SyvernSettings()
    for intent_reference in (
        {"must_include": ["vehicle.engine"]},
        {"must_not_include": ["aircraft.wing"]},
    ):
        result = evaluate_intent("   ", intent_reference, settings)
        assert result.evaluated is False
        assert result.score is None
        assert result.source is None


def test_phrase_matching_does_not_match_inside_larger_words():
    result = evaluate_intent(
        "part engineering.notes attribute massive.object",
        {"must_include": ["engine", "mass"]},
        SyvernSettings(),
    )

    assert result.evaluated is True
    assert result.score is not None
    assert result.score < 3.0


def test_vote_count_must_be_positive():
    with pytest.raises(ValueError, match="intent_vote_count"):
        SyvernSettings(intent_vote_count=0)
