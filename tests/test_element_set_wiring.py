from pathlib import Path

from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult
from syvern.models import ElementSummary, ErrorDetail
from syvern.pipeline import ValidationPipeline


class FakeElementAdapter:
    name = "fake-element-adapter"

    def __init__(self) -> None:
        self.parse_calls: list[str] = []

    def fingerprint(self) -> str:
        return "fake-element-adapter@1"

    def parse(self, text: str) -> ParseResult:
        self.parse_calls.append(text)
        if "broken" in text:
            return ParseResult(
                ok=False,
                errors=[
                    ErrorDetail(
                        stage="parse",
                        code="PARSE_BROKEN",
                        message="synthetic syntax-aware failure",
                    )
                ],
                element_summary=[],
            )
        if "wing" in text:
            return ParseResult(
                ok=True,
                errors=[],
                element_summary=[
                    ElementSummary(type="part", qualified_name="vehicle.wing"),
                    ElementSummary(type="attribute", qualified_name="vehicle.span"),
                ],
            )
        return ParseResult(
            ok=True,
            errors=[],
            element_summary=[
                ElementSummary(type="part", qualified_name="vehicle.engine"),
                ElementSummary(type="attribute", qualified_name="vehicle.mass"),
            ],
        )

    def resolve(self, text: str) -> ResolveResult:
        return ResolveResult(ok=True, unresolved_refs=0, errors=[])

    def typecheck(self, text: str) -> TypecheckResult:
        return TypecheckResult(ok=True, type_errors=0, errors=[])


class AgreeingMontiCoreAdapter:
    name = "agreeing-monticore"

    def fingerprint(self) -> str:
        return "agreeing-monticore@1"

    def parse(self, text: str) -> ParseResult:
        return ParseResult(
            ok=True,
            errors=[],
            element_summary=[
                ElementSummary(type="part", qualified_name="vehicle.engine"),
                ElementSummary(type="attribute", qualified_name="vehicle.mass"),
            ],
        )

    def resolve(self, text: str) -> ResolveResult:
        return ResolveResult(ok=True, unresolved_refs=0, errors=[])

    def typecheck(self, text: str) -> TypecheckResult:
        return TypecheckResult(ok=True, type_errors=0, errors=[])

    def parser_agrees(self, text: str, pilot) -> bool:
        return True


def _reference() -> dict:
    return {
        "elements": [
            {"type": "part", "qualified_name": "vehicle.engine"},
            {"type": "attribute", "qualified_name": "vehicle.mass"},
        ],
    }


def test_pipeline_consumes_adapter_elements_for_rules_veto_and_structural():
    response = ValidationPipeline(
        pilot_adapter=FakeElementAdapter(),
        monticore_adapter=AgreeingMontiCoreAdapter(),
    ).validate(
        "plain words with no sysml keywords",
        mode="full",
        reference=_reference(),
    )

    assert response.veto.triggered is False
    assert {violation.rule for violation in response.stage.constraint.violations} == set()
    assert response.structural.evaluated is True
    assert response.structural.f1 == 1.0


def test_pipeline_parses_ipt_perturbations_with_pilot_adapter():
    pilot = FakeElementAdapter()

    response = ValidationPipeline(
        pilot_adapter=pilot,
        monticore_adapter=AgreeingMontiCoreAdapter(),
    ).validate(
        "plain original words",
        mode="full",
        perturbations=["plain equivalent perturbation"],
    )

    assert response.robustness.ipt_consistent is True
    assert pilot.parse_calls == ["plain original words", "plain equivalent perturbation"]


def test_full_mode_parser_agreement_reuses_initial_pilot_parse():
    pilot = FakeElementAdapter()

    response = ValidationPipeline(pilot_adapter=pilot).validate(
        "part vehicle.engine attribute vehicle.mass",
        mode="full",
    )

    assert response.stage.parse.parser_agreement is True
    assert pilot.parse_calls == ["part vehicle.engine attribute vehicle.mass"]


def test_broken_model_scores_below_valid_with_syntax_aware_adapter():
    pipeline = ValidationPipeline(
        pilot_adapter=FakeElementAdapter(),
        monticore_adapter=AgreeingMontiCoreAdapter(),
    )

    valid = pipeline.validate(
        "part def Vehicle { attribute mass : Real; part engine : Engine; }",
        mode="online_reward",
    )
    broken = pipeline.validate(
        "broken part def Vehicle { attribute mass : ;",
        mode="online_reward",
    )

    assert valid.stage.parse.ok is True
    assert broken.stage.parse.ok is False
    assert valid.meta.reward > broken.meta.reward


def test_stub_element_extractor_is_not_imported_by_business_modules():
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in (root / "src" / "syvern").rglob("*.py"):
        if path.name == "stub.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "extract_element_summary" in text:
            offenders.append(path.relative_to(root).as_posix())

    assert offenders == []
