from __future__ import annotations

from dataclasses import replace

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
from syvern.adapters.base import ValidatorAdapter
from syvern.adapters.subset import SubsetPilotAdapter
from syvern.pipeline import ValidationPipeline
from syvern.settings import SyvernSettings


def build_validation_pipeline(settings: SyvernSettings) -> ValidationPipeline:
    backend = _effective_pilot_backend(settings)
    authoritative: ValidatorAdapter | None = None
    if backend == "pilot":
        if not settings.pilot_endpoint:
            raise ValueError("pilot_backend='pilot' requires a pilot endpoint")
        pilot: ValidatorAdapter = _pilot_http_adapter(settings)
    elif backend == "subset":
        pilot = SubsetPilotAdapter()
        # A configured Pilot endpoint runs in parallel as the authoritative L0
        # for `full` mode while the subset serves the fast online path.
        if settings.pilot_endpoint:
            authoritative = _pilot_http_adapter(settings)
    else:
        pilot = PilotStubAdapter()
        if settings.pilot_endpoint:
            authoritative = _pilot_http_adapter(settings)
    monticore = (
        MontiCoreAdapter(
            settings.monticore_endpoint,
            settings.monticore_version,
            settings.monticore_timeout_s,
        )
        if settings.monticore_endpoint
        else MontiCoreStubAdapter()
    )
    formal = None
    if settings.formal_endpoint and settings.formal_tool is not None:
        formal = FormalAdapter(
            tool=settings.formal_tool,
            endpoint=settings.formal_endpoint,
            version=settings.formal_version,
            timeout_s=settings.formal_timeout_s,
        )
    intent_judge = (
        LLMIntentJudgeAdapter(
            endpoint=settings.intent_judge_endpoint,
            model=settings.judge_model,
            rubric_version=settings.rubric_version,
            timeout_s=settings.intent_judge_timeout_s,
        )
        if settings.intent_judge_endpoint
        else None
    )
    structural_matcher = (
        LLMStructuralMatcherAdapter(
            endpoint=settings.structural_matcher_endpoint,
            model=settings.judge_model,
            rubric_version=settings.rubric_version,
            timeout_s=settings.structural_matcher_timeout_s,
        )
        if settings.structural_matcher_endpoint
        else None
    )
    backend_fingerprints = [pilot.fingerprint(), monticore.fingerprint()]
    if authoritative is not None:
        backend_fingerprints.append(f"authoritative:{authoritative.fingerprint()}")
    if formal is not None:
        backend_fingerprints.append(formal.fingerprint())
    if intent_judge is not None:
        backend_fingerprints.append(intent_judge.fingerprint())
    if structural_matcher is not None:
        backend_fingerprints.append(structural_matcher.fingerprint())
    effective_settings = replace(
        settings,
        validator_fingerprint=f"{settings.validator_fingerprint}+backends[{','.join(backend_fingerprints)}]",
    )
    return ValidationPipeline(
        settings=effective_settings,
        pilot_adapter=pilot,
        monticore_adapter=monticore,
        formal_adapter=formal,
        intent_judge=intent_judge,
        structural_matcher=structural_matcher,
        authoritative_adapter=authoritative,
    )


def _effective_pilot_backend(settings: SyvernSettings) -> str:
    if settings.pilot_backend is not None:
        return settings.pilot_backend
    if settings.pilot_endpoint:
        return "pilot"
    if settings.use_subset_parser:
        return "subset"
    return "stub"


def _pilot_http_adapter(settings: SyvernSettings) -> PilotAdapter:
    assert settings.pilot_endpoint is not None
    return PilotAdapter(settings.pilot_endpoint, settings.pilot_version, settings.pilot_timeout_s)


def build_perturbation_generator(settings: SyvernSettings) -> LLMPerturbationAdapter | None:
    if not settings.perturbation_endpoint:
        return None
    return LLMPerturbationAdapter(
        endpoint=settings.perturbation_endpoint,
        model=settings.perturbation_model,
        rubric_version=settings.perturbation_rubric_version,
        timeout_s=settings.perturbation_timeout_s,
    )
