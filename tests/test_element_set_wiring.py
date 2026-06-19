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
        return ParseResult(ok=True, errors=[], element_summary=[])

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
