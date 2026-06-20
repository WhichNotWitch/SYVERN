from __future__ import annotations

import time
from typing import Any

from syvern.adapters.base import ParseResult, element_summary_counter
from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter
from syvern.models import (
    BatchMetaSummary,
    BatchValidateResponse,
    ConstraintStage,
    ElementSummary,
    FormalSummary,
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
from syvern.ipt import evaluate_ipt
from syvern.intent import evaluate_intent
from syvern.normalization import sha256_text
from syvern.reward import compute_reward
from syvern.robustness import aggregate_robustness
from syvern.rules import evaluate_rules
from syvern.settings import SyvernSettings
from syvern.structural import match_structural
from syvern.veto import evaluate_veto


class ValidationPipeline:
    def __init__(
        self,
        settings: SyvernSettings | None = None,
        pilot_adapter: Any | None = None,
        monticore_adapter: Any | None = None,
        formal_adapter: Any | None = None,
        intent_judge: Any | None = None,
        structural_matcher: Any | None = None,
        authoritative_adapter: Any | None = None,
    ) -> None:
        self.settings = settings or SyvernSettings()
        self.pilot = pilot_adapter or PilotStubAdapter()
        self.monticore = monticore_adapter or MontiCoreStubAdapter()
        # Optional authoritative L0 used only for `full` mode (e.g. real Pilot),
        # running in parallel with a primary adapter for full-mode judgement.
        # None => primary is used everywhere.
        self.authoritative = authoritative_adapter
        self.formal_adapter = formal_adapter
        self.intent_judge = intent_judge
        self.structural_matcher = structural_matcher

    def validate(
        self,
        text: str,
        *,
        mode: Mode = "online_reward",
        reference: dict[str, Any] | None = None,
        perturbations: list[str] | None = None,
        intent_reference: dict[str, Any] | None = None,
        formal_properties: list[str] | None = None,
    ) -> ValidateResponse:
        started = time.perf_counter()

        adapter = self._adapter_for(mode)
        parse_result = adapter.parse(text)
        parser_agreement: bool | None = None
        if mode == "full":
            parser_agreement = self._parser_agrees(text, parse_result)

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
            return self._finish(
                text=text,
                elements=parse_result.element_summary,
                adapter=adapter,
                mode=mode,
                stage=stage,
                started=started,
                reference=reference,
                perturbations=perturbations,
                intent_reference=intent_reference,
                formal_properties=formal_properties,
            )

        resolve_result = adapter.resolve(text)
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
            return self._finish(
                text=text,
                elements=parse_result.element_summary,
                adapter=adapter,
                mode=mode,
                stage=stage,
                started=started,
                reference=reference,
                perturbations=perturbations,
                intent_reference=intent_reference,
                formal_properties=formal_properties,
            )

        typecheck_result = adapter.typecheck(text)
        typecheck = TypecheckStage(
            reached=True,
            ok=typecheck_result.ok,
            type_errors=typecheck_result.type_errors,
            errors=typecheck_result.errors,
        )

        violations = evaluate_rules(text, parse_result.element_summary, self.settings)
        constraint = ConstraintStage(reached=True, ok=not violations, violations=violations)
        stage = StageSummary(parse=parse, resolve=resolve, typecheck=typecheck, constraint=constraint)

        return self._finish(
            text=text,
            elements=parse_result.element_summary,
            adapter=adapter,
            mode=mode,
            stage=stage,
            started=started,
            reference=reference,
            perturbations=perturbations,
            intent_reference=intent_reference,
            formal_properties=formal_properties,
        )

    def validate_many(
        self,
        texts: list[str],
        *,
        mode: Mode = "online_reward",
        reference: dict[str, Any] | None = None,
        perturbations: list[str] | None = None,
        intent_reference: dict[str, Any] | None = None,
        formal_properties: list[str] | None = None,
    ) -> BatchValidateResponse:
        if not texts:
            raise ValueError("texts must not be empty")
        responses = [
            self.validate(
                text,
                mode=mode,
                reference=reference,
                perturbations=perturbations,
                intent_reference=intent_reference,
                formal_properties=formal_properties,
            )
            for text in texts
        ]
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
        elements: list[ElementSummary],
        adapter: Any,
        mode: Mode,
        stage: StageSummary,
        started: float,
        reference: dict[str, Any] | None,
        perturbations: list[str] | None,
        intent_reference: dict[str, Any] | None,
        formal_properties: list[str] | None,
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
            elements=elements,
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
                elements,
                reference,
                self.settings,
                soft_matcher=self.structural_matcher,
            )
        robustness = RobustnessSummary()
        ipt_evaluated = (
            mode == "full"
            and perturbations is not None
            and bool(perturbations)
            and semantic_path_passed
            and stage.constraint.reached
            and stage.constraint.ok
            and not veto.triggered
        )
        if ipt_evaluated:
            assert perturbations is not None
            robustness = RobustnessSummary(
                ipt_consistent=evaluate_ipt(
                    original_elements=elements,
                    perturbation_element_sets=[
                        adapter.parse(perturbation).element_summary for perturbation in perturbations
                    ],
                    settings=self.settings,
                )
            )
        intent = IntentSummary()
        intent_evaluated = (
            mode == "full"
            and intent_reference is not None
            and bool(intent_reference)
            and semantic_path_passed
            and stage.constraint.reached
            and stage.constraint.ok
            and not veto.triggered
        )
        if intent_evaluated:
            if self.intent_judge is not None:
                intent = self.intent_judge.judge(text, intent_reference)
            else:
                intent = evaluate_intent(text, intent_reference, self.settings)
        formal = FormalSummary()
        formal_adapter = self.formal_adapter
        if (
            formal_adapter is not None
            and mode == "full"
            and semantic_path_passed
            and stage.constraint.reached
            and stage.constraint.ok
            and not veto.triggered
        ):
            formal = self._formal_summary(
                formal_adapter.analyze(text, formal_properties or [])
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
            robustness=robustness,
            intent=intent,
            formal=formal,
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
        self._apply_data_filter_decision(response)
        return response

    def _adapter_for(self, mode: Mode) -> Any:
        if mode == "full" and self.authoritative is not None:
            return self.authoritative
        return self.pilot

    def _parser_agrees(self, text: str, parse_result: ParseResult) -> bool:
        monticore_result = self.monticore.parse(text)
        return (
            parse_result.ok == monticore_result.ok
            and element_summary_counter(parse_result.element_summary)
            == element_summary_counter(monticore_result.element_summary)
        )

    def _formal_summary(self, result: Any) -> FormalSummary:
        return FormalSummary(
            evaluated=True,
            tool=result.tool,
            status=result.status,
            properties_checked=result.properties_checked,
            conclusions=list(result.conclusions),
            counterexamples=list(result.counterexamples),
        )

    def _apply_data_filter_decision(self, response: ValidateResponse) -> None:
        if response.meta.mode != "data_filter":
            return
        if response.veto.triggered:
            response.meta.data_filter_pass = False
            response.meta.data_filter_reason = "vetoed"
            return
        if not response.tier_summary.t0_pass:
            response.meta.data_filter_pass = False
            response.meta.data_filter_reason = "t0_failed"
            return
        if response.meta.reward < self.settings.data_filter_min_reward:
            response.meta.data_filter_pass = False
            response.meta.data_filter_reason = "reward_below_threshold"
            return
        response.meta.data_filter_pass = True
        response.meta.data_filter_reason = "passed"
