from __future__ import annotations

import time
from typing import Any

from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter, extract_element_summary
from syvern.models import (
    BatchMetaSummary,
    BatchValidateResponse,
    ConstraintStage,
    IntentSummary,
    MetaSummary,
    Mode,
    MonitorSummary,
    ParseStage,
    ResolveStage,
    RobustnessSummary,
    StageSummary,
    StructuralSummary,
    TierSummary,
    TypecheckStage,
    ValidateResponse,
)
from syvern.normalization import sha256_text
from syvern.reward import compute_reward
from syvern.robustness import aggregate_robustness
from syvern.rules import evaluate_rules
from syvern.settings import SyvernSettings
from syvern.structural import match_structural
from syvern.veto import evaluate_veto


class ValidationPipeline:
    def __init__(self, settings: SyvernSettings | None = None) -> None:
        self.settings = settings or SyvernSettings()
        self.pilot = PilotStubAdapter()
        self.monticore = MontiCoreStubAdapter()

    def validate(
        self,
        text: str,
        *,
        mode: Mode = "online_reward",
        reference: dict[str, Any] | None = None,
    ) -> ValidateResponse:
        started = time.perf_counter()

        parse_result = self.pilot.parse(text)
        parser_agreement = True
        if mode == "full":
            parser_agreement = self.monticore.parser_agrees(text, self.pilot)

        parse = ParseStage(
            reached=True,
            ok=parse_result.ok,
            parser_agreement=parser_agreement,
            errors=parse_result.errors,
        )

        if not parse.ok:
            stage = StageSummary(
                parse=parse,
                resolve=ResolveStage(reached=False, ok=False),
                typecheck=TypecheckStage(reached=False, ok=False),
                constraint=ConstraintStage(reached=False, ok=False),
            )
            return self._finish(text=text, mode=mode, stage=stage, started=started, reference=reference)

        resolve_result = self.pilot.resolve(text)
        resolve = ResolveStage(
            reached=True,
            ok=resolve_result.ok,
            unresolved_refs=resolve_result.unresolved_refs,
            errors=resolve_result.errors,
        )

        if not resolve.ok:
            stage = StageSummary(
                parse=parse,
                resolve=resolve,
                typecheck=TypecheckStage(reached=False, ok=False),
                constraint=ConstraintStage(reached=False, ok=False),
            )
            return self._finish(text=text, mode=mode, stage=stage, started=started, reference=reference)

        typecheck_result = self.pilot.typecheck(text)
        typecheck = TypecheckStage(
            reached=True,
            ok=typecheck_result.ok,
            type_errors=typecheck_result.type_errors,
            errors=typecheck_result.errors,
        )

        violations = evaluate_rules(text, self.settings)
        constraint = ConstraintStage(reached=True, ok=not violations, violations=violations)
        stage = StageSummary(parse=parse, resolve=resolve, typecheck=typecheck, constraint=constraint)

        return self._finish(text=text, mode=mode, stage=stage, started=started, reference=reference)

    def validate_many(
        self,
        texts: list[str],
        *,
        mode: Mode = "online_reward",
        reference: dict[str, Any] | None = None,
    ) -> BatchValidateResponse:
        if not texts:
            raise ValueError("texts must not be empty")
        responses = [self.validate(text, mode=mode, reference=reference) for text in texts]
        metrics = aggregate_robustness(responses)
        return BatchValidateResponse(
            sample_count=len(responses),
            pass_at_k=metrics.pass_at_k,
            stable_at_k=metrics.stable_at_k,
            responses=responses,
            meta=BatchMetaSummary(
                mode=mode,
                validator_fingerprint=self.settings.validator_fingerprint,
            ),
        )

    def _finish(
        self,
        *,
        text: str,
        mode: Mode,
        stage: StageSummary,
        started: float,
        reference: dict[str, Any] | None,
    ) -> ValidateResponse:
        semantic_path_passed = (
            stage.parse.reached
            and stage.parse.ok
            and stage.resolve.reached
            and stage.resolve.ok
            and stage.typecheck.reached
            and stage.typecheck.ok
        )
        veto = evaluate_veto(
            text=text,
            settings=self.settings,
            semantic_path_passed=semantic_path_passed,
            parser_agreement=stage.parse.parser_agreement,
            violations=stage.constraint.violations if stage.constraint.reached else [],
        )
        structural = StructuralSummary(matching_policy_id=self.settings.matching_policy_id)
        structural_evaluated = (
            mode == "full"
            and reference is not None
            and semantic_path_passed
            and stage.constraint.reached
            and stage.constraint.ok
            and not veto.triggered
        )
        if structural_evaluated:
            structural = match_structural(
                extract_element_summary(text),
                reference,
                self.settings,
            )
        tier_summary = TierSummary(
            t0_pass=semantic_path_passed and stage.constraint.ok and not veto.triggered,
            t1_available=structural.evaluated,
            veto=veto.triggered,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        response = ValidateResponse(
            sample_id=sha256_text(text),
            tier_summary=tier_summary,
            stage=stage,
            structural=structural,
            robustness=RobustnessSummary(),
            intent=IntentSummary(),
            veto=veto,
            monitor=MonitorSummary(),
            meta=MetaSummary(
                latency_ms=latency_ms,
                mode=mode,
                validator_fingerprint=self.settings.validator_fingerprint,
                reward=0.0,
                text_hash=sha256_text(text),
                cache_hit=False,
            ),
        )
        response.meta.reward = compute_reward(response, self.settings)
        return response
