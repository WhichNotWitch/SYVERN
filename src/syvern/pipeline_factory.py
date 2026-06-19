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
from syvern.pipeline import ValidationPipeline
from syvern.settings import SyvernSettings


def build_validation_pipeline(settings: SyvernSettings) -> ValidationPipeline:
    pilot = (
        PilotAdapter(settings.pilot_endpoint, settings.pilot_version, settings.pilot_timeout_s)
        if settings.pilot_endpoint
        else PilotStubAdapter()
    )
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
    )


def build_perturbation_generator(settings: SyvernSettings) -> LLMPerturbationAdapter | None:
    if not settings.perturbation_endpoint:
        return None
    return LLMPerturbationAdapter(
        endpoint=settings.perturbation_endpoint,
        model=settings.perturbation_model,
        rubric_version=settings.perturbation_rubric_version,
        timeout_s=settings.perturbation_timeout_s,
    )
