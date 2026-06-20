from syvern.adapters.formal import FormalResult
from syvern.models import IntentSummary
from syvern.pipeline import ValidationPipeline
from syvern.settings import SyvernSettings


class FakeFormalAdapter:
    def __init__(self, result: FormalResult) -> None:
        self.result = result
        self.calls: list[tuple[str, list[str]]] = []

    def analyze(self, text: str, properties: list[str] | None = None) -> FormalResult:
        self.calls.append((text, properties or []))
        return self.result


class FakeIntentJudge:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[tuple[str, dict]] = []

    def judge(self, text: str, intent_reference: dict) -> IntentSummary:
        self.calls.append((text, intent_reference))
        return IntentSummary(evaluated=True, score=self.score, source="llm_judge")


class FakeStructuralMatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def match(self, generated, reference) -> bool:
        self.calls.append((generated.qualified_name, reference.qualified_name))
        return generated.qualified_name == "vehicle.motor" and reference.qualified_name == "vehicle.engine"


def test_syntax_error_blocks_later_stages():
    response = ValidationPipeline().validate("syntax_error", mode="online_reward")
    assert not response.stage.parse.ok
    assert not response.stage.resolve.reached
    assert not response.stage.typecheck.reached
    assert not response.stage.constraint.reached


def test_unresolved_ref_blocks_typecheck_and_constraints():
    response = ValidationPipeline().validate("part A unresolved_ref", mode="online_reward")
    assert response.stage.parse.ok
    assert response.stage.resolve.reached
    assert not response.stage.resolve.ok
    assert not response.stage.typecheck.reached
    assert not response.stage.constraint.reached


def test_type_error_still_reaches_constraints():
    response = ValidationPipeline().validate("part A type_error", mode="online_reward")
    assert response.stage.typecheck.reached
    assert not response.stage.typecheck.ok
    assert response.stage.constraint.reached


def test_full_mode_parser_disagreement_triggers_veto():
    response = ValidationPipeline().validate("part A parser_disagreement", mode="full")
    assert response.stage.parse.parser_agreement is False
    assert response.veto.triggered
    assert response.meta.reward == 0.0


def test_short_semantic_pass_triggers_degenerate_veto():
    response = ValidationPipeline().validate("part A", mode="online_reward")

    assert response.veto.triggered is True
    assert response.veto.reason == "degenerate_output"
    assert response.meta.reward == 0.0


def test_semantic_pass_with_empty_curated_element_set_is_not_degenerate():
    # Bug2: a model that fully passes the semantic path but extracts no element
    # from the *curated* structural subset (e.g. metadata-only / behavioral-only
    # models) must NOT be vetoed as degenerate.
    response = ValidationPipeline().validate("comment only enough tokens", mode="online_reward")

    assert response.stage.parse.ok is True
    assert response.stage.resolve.ok is True
    assert response.stage.typecheck.ok is True
    assert response.veto.triggered is False
    assert response.meta.reward > 0.0
    assert "minimum_element_signal" not in {v.rule for v in response.stage.constraint.violations}


def test_filler_markers_trigger_anti_gaming_veto():
    for text in ("part A todo marker", "part A tbd marker"):
        response = ValidationPipeline().validate(text, mode="online_reward")

        assert response.veto.triggered is True
        assert response.veto.reason == "anti_gaming_rule"
        assert response.meta.reward == 0.0
        assert any(v.rule == "no_filler_text" for v in response.stage.constraint.violations)


def test_h1_non_h1_fields_are_unevaluated_defaults():
    response = ValidationPipeline().validate("part A attribute x", mode="full")
    assert response.structural.evaluated is False
    assert response.structural.matching_policy_id == "h9-normalized-fuzzy-v1"
    assert response.intent.evaluated is False
    assert response.robustness.ipt_consistent is None
    assert response.formal.evaluated is False
    assert response.formal.status is None


def test_full_mode_summary_disagreement_triggers_veto():
    response = ValidationPipeline().validate("part A summary_disagreement", mode="full")

    assert response.stage.parse.ok is True
    assert response.stage.parse.parser_agreement is False
    assert response.veto.triggered is True
    assert response.veto.reason == "parser_disagreement"
    assert response.meta.reward == 0.0


def test_online_reward_does_not_run_summary_disagreement_check():
    response = ValidationPipeline().validate("part A summary_disagreement", mode="online_reward")

    assert response.stage.parse.parser_agreement is None
    assert response.veto.reason != "parser_disagreement"


def test_online_reward_marks_parser_agreement_unknown_without_penalizing_parse_reward():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")

    assert response.stage.parse.parser_agreement is None
    assert response.veto.triggered is False
    assert response.meta.reward > 0.0
    assert response.meta.data_filter_pass is None
    assert response.meta.data_filter_reason is None


def test_data_filter_passes_t0_clean_sample_above_reward_threshold():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="data_filter",
    )

    assert response.tier_summary.t0_pass is True
    assert response.meta.data_filter_pass is True
    assert response.meta.data_filter_reason == "passed"


def test_data_filter_drops_t0_failure_before_reward_threshold():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass type_error",
        mode="data_filter",
    )

    assert response.tier_summary.t0_pass is False
    assert response.meta.data_filter_pass is False
    assert response.meta.data_filter_reason == "t0_failed"


def test_data_filter_drops_vetoed_samples():
    response = ValidationPipeline().validate("part A todo marker", mode="data_filter")

    assert response.veto.triggered is True
    assert response.meta.data_filter_pass is False
    assert response.meta.data_filter_reason == "vetoed"


def test_data_filter_drops_t0_pass_below_reward_threshold():
    settings = SyvernSettings(data_filter_min_reward=0.95)
    response = ValidationPipeline(settings=settings).validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="data_filter",
    )

    assert response.tier_summary.t0_pass is True
    assert response.meta.reward < settings.data_filter_min_reward
    assert response.meta.data_filter_pass is False
    assert response.meta.data_filter_reason == "reward_below_threshold"


def test_validate_many_returns_batch_response_with_metrics_in_request_order():
    pipeline = ValidationPipeline()
    result = pipeline.validate_many(
        [
            "part A attribute x",
            "part B unresolved_ref",
            "part C type_error",
        ],
        mode="online_reward",
    )

    assert result.sample_count == 3
    assert result.pass_at_k == 1.0
    assert result.stable_at_k == 1 / 3
    assert [response.meta.text_hash for response in result.responses] == [
        pipeline.validate("part A attribute x", mode="online_reward").meta.text_hash,
        pipeline.validate("part B unresolved_ref", mode="online_reward").meta.text_hash,
        pipeline.validate("part C type_error", mode="online_reward").meta.text_hash,
    ]


def _reference():
    return {
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


def test_full_mode_with_reference_evaluates_structural_stage():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
    )

    assert response.structural.evaluated is True
    assert response.structural.precision == 1.0
    assert response.structural.recall == 1.0
    assert response.structural.f1 == 1.0
    assert response.structural.requirement_coverage == 1.0
    assert response.structural.hallucinated_elements == 0
    assert response.structural.matching_policy_id == "h9-normalized-fuzzy-v1"
    assert response.tier_summary.t1_available is True
    assert response.meta.reward == 1.0


def test_full_mode_can_use_injected_soft_structural_matcher():
    matcher = FakeStructuralMatcher()

    response = ValidationPipeline(structural_matcher=matcher).validate(
        "part vehicle.motor attribute vehicle.mass",
        mode="full",
        reference=_reference(),
    )

    assert matcher.calls == [("vehicle.motor", "vehicle.engine")]
    assert response.structural.soft_matched == 1
    assert response.structural.f1 == 1.0
    assert response.structural.hallucinated_elements == 0


def test_soft_structural_matcher_is_skipped_outside_full_structural_evaluation():
    matcher = FakeStructuralMatcher()
    pipeline = ValidationPipeline(structural_matcher=matcher)

    pipeline.validate("part vehicle.motor attribute vehicle.mass", mode="online_reward", reference=_reference())
    pipeline.validate(
        "part vehicle.motor attribute vehicle.mass type_error",
        mode="full",
        reference=_reference(),
    )
    pipeline.validate(
        "part vehicle.motor attribute vehicle.mass summary_disagreement",
        mode="full",
        reference=_reference(),
    )

    assert matcher.calls == []


def test_full_mode_with_equivalent_perturbations_sets_ipt_consistent():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
        perturbations=["attribute vehicle.mass part vehicle.engine"],
    )

    assert response.structural.evaluated is True
    assert response.robustness.ipt_consistent is True


def test_full_mode_ipt_compares_perturbations_to_original_output_without_reference():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        perturbations=["attribute vehicle.mass part vehicle.engine"],
    )

    assert response.structural.evaluated is False
    assert response.robustness.ipt_consistent is True


def test_full_mode_ipt_does_not_compare_perturbations_to_external_reference():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference={
            "elements": [
                {"type": "part", "qualified_name": "aircraft.wing"},
                {"type": "attribute", "qualified_name": "aircraft.span"},
            ],
        },
        perturbations=["part vehicle.engine attribute vehicle.mass"],
    )

    assert response.structural.evaluated is True
    assert response.structural.f1 < 1.0
    assert response.robustness.ipt_consistent is True


def test_full_mode_with_structural_perturbation_failure_sets_ipt_false():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
        perturbations=["part vehicle.engine"],
    )

    assert response.structural.evaluated is True
    assert response.robustness.ipt_consistent is False


def test_missing_perturbations_leave_ipt_unevaluated():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
    )

    assert response.robustness.ipt_consistent is None


def test_online_reward_and_data_filter_do_not_run_ipt():
    for mode in ("online_reward", "data_filter"):
        response = ValidationPipeline().validate(
            "part vehicle.engine attribute vehicle.mass",
            mode=mode,
            reference=_reference(),
            perturbations=["attribute vehicle.mass part vehicle.engine"],
        )

        assert response.structural.evaluated is False
        assert response.robustness.ipt_consistent is None


def test_t0_failure_or_veto_prevents_ipt_evaluation():
    type_failure = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass type_error",
        mode="full",
        reference=_reference(),
        perturbations=["attribute vehicle.mass part vehicle.engine"],
    )
    vetoed = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass summary_disagreement",
        mode="full",
        reference=_reference(),
        perturbations=["attribute vehicle.mass part vehicle.engine"],
    )

    assert type_failure.robustness.ipt_consistent is None
    assert vetoed.veto.triggered is True
    assert vetoed.robustness.ipt_consistent is None


def test_full_mode_without_reference_keeps_structural_unevaluated():
    response = ValidationPipeline().validate("part vehicle.engine attribute vehicle.mass", mode="full")

    assert response.structural.evaluated is False
    assert response.structural.f1 == 0.0
    assert response.tier_summary.t1_available is False


def test_online_reward_and_data_filter_do_not_evaluate_structural_stage():
    for mode in ("online_reward", "data_filter"):
        response = ValidationPipeline().validate(
            "part vehicle.engine attribute vehicle.mass",
            mode=mode,
            reference=_reference(),
        )

        assert response.structural.evaluated is False
        assert response.tier_summary.t1_available is False


def test_t0_failure_or_veto_prevents_structural_evaluation():
    type_failure = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass type_error",
        mode="full",
        reference=_reference(),
    )
    vetoed = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass summary_disagreement",
        mode="full",
        reference=_reference(),
    )

    assert type_failure.structural.evaluated is False
    assert vetoed.veto.triggered is True
    assert vetoed.structural.evaluated is False


def test_validate_many_forwards_reference_to_each_full_response():
    result = ValidationPipeline().validate_many(
        ["part vehicle.engine attribute vehicle.mass"],
        mode="full",
        reference=_reference(),
    )

    assert result.responses[0].structural.evaluated is True
    assert result.responses[0].structural.f1 == 1.0


def _intent_reference():
    return {
        "requirements": ["model engine", "include mass"],
        "must_include": ["vehicle.engine", "vehicle.mass"],
        "must_not_include": ["aircraft.wing"],
    }


def test_full_mode_with_intent_reference_evaluates_intent_without_structural_reference():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        intent_reference=_intent_reference(),
    )

    assert response.intent.evaluated is True
    assert response.intent.source == "heuristic"
    assert response.intent.score is not None
    assert response.intent.score > 3.0
    assert response.structural.evaluated is False


def test_full_mode_can_use_injected_llm_intent_judge_without_reward_effect():
    intent_reference = _intent_reference()
    judge = FakeIntentJudge(score=1.25)
    baseline = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        intent_reference=intent_reference,
    )

    response = ValidationPipeline(intent_judge=judge).validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        intent_reference=intent_reference,
    )

    assert judge.calls == [("part vehicle.engine attribute vehicle.mass", intent_reference)]
    assert response.intent.evaluated is True
    assert response.intent.source == "llm_judge"
    assert response.intent.score == 1.25
    assert response.meta.reward == baseline.meta.reward


def test_online_reward_and_data_filter_do_not_evaluate_intent():
    for mode in ("online_reward", "data_filter"):
        response = ValidationPipeline().validate(
            "part vehicle.engine attribute vehicle.mass",
            mode=mode,
            intent_reference=_intent_reference(),
        )

        assert response.intent.evaluated is False
        assert response.intent.score is None
        assert response.intent.source is None


def test_full_mode_with_formal_adapter_records_offline_result_without_reward_effect():
    formal_adapter = FakeFormalAdapter(
        FormalResult(
            tool="imandra",
            status="failed",
            properties_checked=1,
            conclusions=["mass bound violated"],
            counterexamples=["mass = -1 kg"],
        )
    )
    baseline = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
    )

    response = ValidationPipeline(formal_adapter=formal_adapter).validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
        formal_properties=["req.mass"],
    )

    assert formal_adapter.calls == [
        ("part vehicle.engine attribute vehicle.mass", ["req.mass"])
    ]
    assert response.formal.evaluated is True
    assert response.formal.tool == "imandra"
    assert response.formal.status == "failed"
    assert response.formal.properties_checked == 1
    assert response.formal.conclusions == ["mass bound violated"]
    assert response.formal.counterexamples == ["mass = -1 kg"]
    assert response.meta.reward == baseline.meta.reward


def test_formal_adapter_is_skipped_outside_full_mode_and_on_t0_failure_or_veto():
    formal_adapter = FakeFormalAdapter(
        FormalResult(tool="gamma", status="proved", properties_checked=1)
    )
    pipeline = ValidationPipeline(formal_adapter=formal_adapter)

    online = pipeline.validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="online_reward",
        formal_properties=["req.mass"],
    )
    type_failure = pipeline.validate(
        "part vehicle.engine attribute vehicle.mass type_error",
        mode="full",
        formal_properties=["req.mass"],
    )
    vetoed = pipeline.validate(
        "part vehicle.engine attribute vehicle.mass summary_disagreement",
        mode="full",
        formal_properties=["req.mass"],
    )

    assert formal_adapter.calls == []
    assert online.formal.evaluated is False
    assert type_failure.formal.evaluated is False
    assert vetoed.formal.evaluated is False


def test_t0_failure_prevents_intent_evaluation():
    response = ValidationPipeline().validate(
        "syntax_error",
        mode="full",
        intent_reference=_intent_reference(),
    )

    assert response.intent.evaluated is False
    assert response.intent.score is None


def test_veto_prevents_intent_evaluation():
    response = ValidationPipeline().validate(
        "dummy dummy dummy dummy",
        mode="full",
        intent_reference=_intent_reference(),
    )

    assert response.veto.triggered is True
    assert response.intent.evaluated is False
