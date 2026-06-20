from typing import Literal

from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter, extract_element_summary
from syvern.models import (
    ConstraintStage,
    IntentSummary,
    MonitorSummary,
    ParseStage,
    ResolveStage,
    RobustnessSummary,
    StageSummary,
    StructuralSummary,
    TierSummary,
    TypecheckStage,
    ValidateResponse,
    VetoSummary,
)
from syvern.pipeline import ValidationPipeline
from syvern.reward import compute_reward
from syvern.rules import evaluate_rules, weighted_violations
from syvern.settings import RewardWeights, SyvernSettings
from syvern.veto import evaluate_veto


def _elements(text: str):
    return extract_element_summary(text)


def _evaluate_rules(text: str, settings: SyvernSettings | None = None):
    resolved_settings = settings or SyvernSettings()
    return evaluate_rules(text, _elements(text), resolved_settings)


def _response(
    intent_score: float | None = None,
    intent_source: Literal["heuristic", "llm_judge", "human"] | None = None,
    intent_evaluated: bool | None = None,
    veto: bool = False,
    stage: StageSummary | None = None,
    structural: StructuralSummary | None = None,
    robustness: RobustnessSummary | None = None,
) -> ValidateResponse:
    settings = SyvernSettings()
    stage = stage or StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )
    return ValidateResponse(
        sample_id="sample",
        tier_summary=TierSummary(t0_pass=True, t1_available=False, veto=veto),
        stage=stage,
        structural=structural or StructuralSummary(matching_policy_id=settings.matching_policy_id),
        robustness=robustness or RobustnessSummary(),
        intent=IntentSummary(
            evaluated=(intent_score is not None) if intent_evaluated is None else intent_evaluated,
            score=intent_score,
            source=intent_source,
        ),
        veto=VetoSummary(triggered=veto, reason="forced" if veto else None),
        monitor=MonitorSummary(),
        meta={
            "latency_ms": 0,
            "mode": "online_reward",
            "validator_fingerprint": settings.validator_fingerprint,
            "reward": 0.0,
            "text_hash": "hash",
            "cache_hit": False,
        },
    )


def test_stub_adapter_reports_triggered_failures():
    adapter = PilotStubAdapter()
    assert not adapter.parse("syntax_error").ok
    assert adapter.resolve("unresolved_ref").unresolved_refs == 1
    assert adapter.typecheck("type_error").type_errors == 1


def test_monticore_stub_disagrees_on_marker():
    pilot = PilotStubAdapter()
    monticore = MontiCoreStubAdapter()
    assert not monticore.parser_agrees("part A parser_disagreement", pilot)


def test_anti_gaming_rules_are_weighted():
    violations = _evaluate_rules("filler filler filler", SyvernSettings())
    assert any(v.rule == "no_filler_text" for v in violations)
    assert weighted_violations(violations) >= 2


def test_filler_marker_rules_include_h1_spec_markers():
    settings = SyvernSettings()
    for marker in ("todo", "tbd", "filler", "dummy", "???"):
        violations = _evaluate_rules(f"part A {marker} marker", settings)
        assert any(v.rule == "no_filler_text" for v in violations)


def test_filler_marker_in_qualified_name_is_not_gaming():
    # `StatusKind::tbd` is a legitimate SysML enum value, not filler text.
    violations = _evaluate_rules("part A attribute status = StatusKind::tbd", SyvernSettings())
    assert not any(v.rule == "no_filler_text" for v in violations)


def test_filler_marker_in_comment_is_not_gaming():
    text = "part A attribute x // StatusKind has values for open, closed, tbd, tbr"
    violations = _evaluate_rules(text, SyvernSettings())
    assert not any(v.rule == "no_filler_text" for v in violations)


def test_filler_marker_in_block_comment_and_string_is_not_gaming():
    text = 'part A /* todo: revisit */ attribute label = "fill in ??? later"'
    violations = _evaluate_rules(text, SyvernSettings())
    assert not any(v.rule == "no_filler_text" for v in violations)


def test_standalone_filler_marker_still_flags_in_model_substance():
    violations = _evaluate_rules("part A tbd attribute x", SyvernSettings())
    assert any(v.rule == "no_filler_text" for v in violations)


def test_repetition_rule_applies_below_min_tokens():
    violations = _evaluate_rules("x x", SyvernSettings())
    rules = {v.rule for v in violations}
    assert "no_excessive_repetition" in rules
    assert "minimum_model_signal" in rules


def test_placeholder_element_names_trigger_anti_gaming_rule():
    violations = _evaluate_rules("part item1 attribute placeholder", SyvernSettings())
    assert any(v.rule == "no_placeholder_names" for v in violations)


def test_enumeration_style_elements_trigger_anti_gaming_rule():
    text = "part wheel1 part wheel2 part wheel3 part wheel4"
    violations = _evaluate_rules(text, SyvernSettings())
    assert any(v.rule == "no_enumeration_gaming" for v in violations)


def test_pipeline_vetoes_enumeration_style_output():
    response = ValidationPipeline().validate(
        "part wheel1 part wheel2 part wheel3 part wheel4",
        mode="online_reward",
    )

    assert response.veto.triggered is True
    assert response.veto.reason == "anti_gaming_rule"
    assert response.meta.reward == 0.0
    assert any(v.rule == "no_enumeration_gaming" for v in response.stage.constraint.violations)


def test_empty_curated_element_set_does_not_produce_element_signal_violation():
    # Bug2: 0 curated elements is not an anti-gaming signal — valid metadata-only
    # / behavioral-only models legitimately extract no element from the subset.
    violations = _evaluate_rules("comment only enough tokens", SyvernSettings())
    assert "minimum_element_signal" not in {v.rule for v in violations}


def test_veto_triggers_for_error_anti_gaming_rule():
    settings = SyvernSettings()
    text = "filler filler filler"
    violations = _evaluate_rules(text, settings)
    veto = evaluate_veto(
        text=text,
        elements=_elements(text),
        settings=settings,
        semantic_path_passed=True,
        parser_agreement=True,
        violations=violations,
    )
    assert veto.triggered
    assert veto.reason == "anti_gaming_rule"


def test_veto_ignores_unknown_parser_agreement():
    text = "part A attribute x"
    veto = evaluate_veto(
        text=text,
        elements=_elements(text),
        settings=SyvernSettings(),
        semantic_path_passed=True,
        parser_agreement=None,
        violations=[],
    )

    assert veto.triggered is False
    assert veto.reason is None


def test_semantic_pass_with_empty_curated_element_set_is_not_vetoed():
    # Bug2: enough tokens + full semantic path, but 0 curated elements (e.g. a
    # metadata-only or behavioral-only model) must NOT trigger degenerate_output.
    veto = evaluate_veto(
        text="plain words with enough tokens but no curated elements",
        elements=[],
        settings=SyvernSettings(),
        semantic_path_passed=True,
        parser_agreement=True,
        violations=[],
    )
    assert veto.triggered is False
    assert veto.reason is None


def test_token_trivial_semantic_pass_still_triggers_degenerate_veto():
    # The token-based degeneracy guard remains: genuinely trivial output is
    # still vetoed even when it slips through the semantic path.
    veto = evaluate_veto(
        text="x",
        elements=[],
        settings=SyvernSettings(),
        semantic_path_passed=True,
        parser_agreement=True,
        violations=[],
    )
    assert veto.triggered is True
    assert veto.reason == "degenerate_output"


def test_reward_is_zero_when_veto_triggers():
    assert compute_reward(_response(veto=True), SyvernSettings()) == 0.0


def test_intent_score_does_not_affect_reward():
    settings = SyvernSettings()
    low = compute_reward(_response(intent_score=0.0), settings)
    high = compute_reward(_response(intent_score=5.0), settings)
    assert low == high


def test_reward_ignores_evaluated_intent_source_and_score():
    settings = SyvernSettings()
    unevaluated = compute_reward(
        _response(intent_score=None, intent_source=None, intent_evaluated=False),
        settings,
    )
    llm_high = compute_reward(
        _response(intent_score=5.0, intent_source="llm_judge", intent_evaluated=True),
        settings,
    )
    heuristic_mid = compute_reward(
        _response(intent_score=3.0, intent_source="heuristic", intent_evaluated=True),
        settings,
    )
    human_low = compute_reward(
        _response(intent_score=0.0, intent_source="human", intent_evaluated=True),
        settings,
    )

    assert unevaluated == llm_high == heuristic_mid == human_low


def test_reward_does_not_credit_downstream_when_parse_fails():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=False, parser_agreement=False, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == 0.0


def test_reward_does_not_credit_downstream_when_parser_disagrees():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=False, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == 0.0


def test_reward_credits_parse_when_parser_agreement_is_unknown():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=None, errors=[]),
        resolve=ResolveStage(reached=False, ok=False, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=False, ok=False, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=False, ok=False, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == settings.weights.w0


def test_reward_does_not_credit_unreached_typecheck_or_constraint_after_resolve_failure():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=False, unresolved_refs=1, errors=[]),
        typecheck=TypecheckStage(reached=False, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=False, ok=True, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == settings.weights.w0


def test_reward_credits_reached_typecheck_and_only_reached_constraint():
    settings = SyvernSettings()
    stage_without_constraint = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=False, type_errors=2, errors=[]),
        constraint=ConstraintStage(reached=False, ok=True, violations=[]),
    )
    stage_with_constraint = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=False, type_errors=2, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )
    typecheck_credit = settings.weights.w2 * (1 - 2 / settings.cap_type)

    assert compute_reward(_response(stage=stage_without_constraint), settings) == (
        settings.weights.w0 + settings.weights.w1 + typecheck_credit
    )
    assert compute_reward(_response(stage=stage_with_constraint), settings) == (
        settings.weights.w0 + settings.weights.w1 + typecheck_credit + settings.weights.w3
    )


def test_reward_does_not_credit_positive_t1_terms_when_t0_fails():
    settings = SyvernSettings(weights=RewardWeights(w6=0.05))
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=False, type_errors=1, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )
    structural = StructuralSummary(
        f1=1.0,
        requirement_coverage=1.0,
        matching_policy_id=settings.matching_policy_id,
    )
    robustness = RobustnessSummary(ipt_consistent=True)
    typecheck_credit = settings.weights.w2 * (1 - 1 / settings.cap_type)
    expected_without_t1 = settings.weights.w0 + settings.weights.w1 + typecheck_credit + settings.weights.w3
    would_include_t1 = expected_without_t1 + settings.weights.w4 + settings.weights.w5 + settings.weights.w6

    reward = compute_reward(_response(stage=stage, structural=structural, robustness=robustness), settings)

    assert reward == expected_without_t1
    assert reward < would_include_t1


def test_reward_credits_w6_only_when_ipt_is_consistent_and_t0_passes():
    settings = SyvernSettings(weights=RewardWeights(w6=0.07))
    consistent = compute_reward(_response(robustness=RobustnessSummary(ipt_consistent=True)), settings)
    inconsistent = compute_reward(_response(robustness=RobustnessSummary(ipt_consistent=False)), settings)
    unevaluated = compute_reward(_response(robustness=RobustnessSummary(ipt_consistent=None)), settings)

    assert consistent == inconsistent + settings.weights.w6
    assert inconsistent == unevaluated
