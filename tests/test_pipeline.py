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
    assert response.structural.matching_policy_id == "h1-not-evaluated"
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
