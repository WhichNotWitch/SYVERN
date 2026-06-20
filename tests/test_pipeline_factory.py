from syvern.adapters import (
    FormalAdapter,
    LLMIntentJudgeAdapter,
    LLMPerturbationAdapter,
    LLMStructuralMatcherAdapter,
    MontiCoreAdapter,
    MontiCoreStubAdapter,
    PilotAdapter,
    PilotStubAdapter,
)
from syvern.pipeline_factory import build_perturbation_generator, build_validation_pipeline
from syvern.settings import SyvernSettings


def test_build_validation_pipeline_uses_stub_adapters_by_default():
    pipeline = build_validation_pipeline(SyvernSettings())

    assert isinstance(pipeline.pilot, PilotStubAdapter)
    assert isinstance(pipeline.monticore, MontiCoreStubAdapter)
    assert pipeline.formal_adapter is None
    assert pipeline.intent_judge is None
    assert pipeline.structural_matcher is None


def test_build_validation_pipeline_uses_subset_parser_when_enabled():
    from syvern.adapters.subset import SubsetPilotAdapter

    pipeline = build_validation_pipeline(SyvernSettings(use_subset_parser=True))

    assert isinstance(pipeline.pilot, SubsetPilotAdapter)
    assert pipeline.authoritative is None


def test_subset_primary_runs_in_parallel_with_authoritative_pilot():
    from syvern.adapters.subset import SubsetPilotAdapter

    pipeline = build_validation_pipeline(
        SyvernSettings(pilot_backend="subset", pilot_endpoint="http://pilot.local")
    )

    # fast in-process subset is the primary (online); real Pilot is authoritative (full)
    assert isinstance(pipeline.pilot, SubsetPilotAdapter)
    assert isinstance(pipeline.authoritative, PilotAdapter)


def test_explicit_pilot_backend_requires_endpoint():
    import pytest

    with pytest.raises(ValueError):
        build_validation_pipeline(SyvernSettings(pilot_backend="pilot"))


def test_build_validation_pipeline_wires_configured_http_adapters():
    settings = SyvernSettings(
        pilot_endpoint="http://pilot.local/api",
        pilot_version="2026.1",
        monticore_endpoint="http://monticore.local/api",
        monticore_version="2026.1",
        formal_endpoint="http://formal.local/api",
        formal_tool="imandra",
        formal_version="2026.1",
        intent_judge_endpoint="http://judge.local/api",
        structural_matcher_endpoint="http://matcher.local/api",
        judge_model="judge-model-1",
        rubric_version="rubric-v2",
    )

    pipeline = build_validation_pipeline(settings)

    assert isinstance(pipeline.pilot, PilotAdapter)
    assert pipeline.pilot.endpoint == "http://pilot.local/api"
    assert isinstance(pipeline.monticore, MontiCoreAdapter)
    assert pipeline.monticore.endpoint == "http://monticore.local/api"
    assert isinstance(pipeline.formal_adapter, FormalAdapter)
    assert pipeline.formal_adapter.tool == "imandra"
    assert isinstance(pipeline.intent_judge, LLMIntentJudgeAdapter)
    assert pipeline.intent_judge.endpoint == "http://judge.local/api"
    assert isinstance(pipeline.structural_matcher, LLMStructuralMatcherAdapter)
    assert pipeline.structural_matcher.endpoint == "http://matcher.local/api"


def test_build_validation_pipeline_adds_backend_fingerprints_to_effective_settings():
    settings = SyvernSettings(
        pilot_endpoint="http://pilot.local/api",
        pilot_version="2026.1",
        monticore_endpoint="http://monticore.local/api",
        monticore_version="2026.1",
        intent_judge_endpoint="http://judge.local/api",
        structural_matcher_endpoint="http://matcher.local/api",
        judge_model="judge-model-1",
        rubric_version="rubric-v2",
    )

    pipeline = build_validation_pipeline(settings)

    assert pipeline.settings.validator_fingerprint.startswith(settings.validator_fingerprint)
    assert "pilot@2026.1" in pipeline.settings.validator_fingerprint
    assert "monticore@2026.1" in pipeline.settings.validator_fingerprint
    assert "intent-llm@judge-model-1+rubric@rubric-v2" in pipeline.settings.validator_fingerprint
    assert "structural-llm@judge-model-1+rubric@rubric-v2" in pipeline.settings.validator_fingerprint


def test_build_perturbation_generator_returns_none_without_endpoint():
    assert build_perturbation_generator(SyvernSettings()) is None


def test_build_perturbation_generator_wires_configured_http_adapter():
    settings = SyvernSettings(
        perturbation_endpoint="http://perturb.local/api",
        perturbation_model="perturb-model-1",
        perturbation_rubric_version="ipt-rubric-v1",
        perturbation_timeout_s=3.0,
    )

    generator = build_perturbation_generator(settings)

    assert isinstance(generator, LLMPerturbationAdapter)
    assert generator.endpoint == "http://perturb.local/api"
    assert generator.model == "perturb-model-1"
    assert generator.rubric_version == "ipt-rubric-v1"
    assert generator.timeout_s == 3.0
