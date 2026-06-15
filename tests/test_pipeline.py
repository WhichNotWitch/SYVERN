from syvern.pipeline import ValidationPipeline


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


def test_semantic_pass_with_too_few_elements_triggers_degenerate_veto():
    response = ValidationPipeline().validate("comment only enough tokens", mode="online_reward")

    assert response.stage.parse.ok is True
    assert response.stage.resolve.ok is True
    assert response.stage.typecheck.ok is True
    assert response.veto.triggered is True
    assert response.veto.reason == "degenerate_output"
    assert response.meta.reward == 0.0


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
    assert response.structural.matching_policy_id == "h3-frozen-exact-v1"
    assert response.intent.evaluated is False
    assert response.robustness.ipt_consistent is None


def test_full_mode_summary_disagreement_triggers_veto():
    response = ValidationPipeline().validate("part A summary_disagreement", mode="full")

    assert response.stage.parse.ok is True
    assert response.stage.parse.parser_agreement is False
    assert response.veto.triggered is True
    assert response.veto.reason == "parser_disagreement"
    assert response.meta.reward == 0.0


def test_online_reward_does_not_run_summary_disagreement_check():
    response = ValidationPipeline().validate("part A summary_disagreement", mode="online_reward")

    assert response.stage.parse.parser_agreement is True
    assert response.veto.reason != "parser_disagreement"


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
    assert response.structural.matching_policy_id == "h3-frozen-exact-v1"
    assert response.tier_summary.t1_available is True
    assert response.meta.reward == 1.0


def test_full_mode_with_equivalent_perturbations_sets_ipt_consistent():
    response = ValidationPipeline().validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
        reference=_reference(),
        perturbations=["attribute vehicle.mass part vehicle.engine"],
    )

    assert response.structural.evaluated is True
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
    assert response.intent.source == "llm_judge"
    assert response.intent.score is not None
    assert response.intent.score > 3.0
    assert response.structural.evaluated is False


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
