from __future__ import annotations

import re

from syvern.adapters.base import (
    ParseResult,
    ResolveResult,
    TypecheckResult,
    ValidatorAdapter,
    element_summary_counter,
)
from syvern.models import ElementSummary, ErrorDetail
from syvern.normalization import normalize_ws


ELEMENT_PATTERN = re.compile(
    r"\b(part|attribute|connection|requirement|item|action)\s+([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


def extract_element_summary(text: str) -> list[ElementSummary]:
    return [
        ElementSummary(type=match.group(1), qualified_name=match.group(2))
        for match in ELEMENT_PATTERN.finditer(normalize_ws(text))
    ]


class PilotStubAdapter:
    name = "pilot-stub"

    def fingerprint(self) -> str:
        return "pilot-stub@0.6.0"

    def parse(self, text: str) -> ParseResult:
        normalized = normalize_ws(text)
        if not normalized:
            return ParseResult(
                False,
                [ErrorDetail(stage="parse", code="PARSE_EMPTY_INPUT", message="Input text is empty")],
            )
        if "syntax_error" in normalized:
            return ParseResult(
                False,
                [ErrorDetail(stage="parse", code="PARSE_SYNTAX_ERROR", message="Synthetic syntax error marker")],
            )
        return ParseResult(True, [], extract_element_summary(normalized))

    def resolve(self, text: str) -> ResolveResult:
        if "unresolved_ref" in normalize_ws(text):
            return ResolveResult(
                False,
                1,
                [
                    ErrorDetail(
                        stage="resolve",
                        code="RESOLVE_UNRESOLVED_REF",
                        message="Synthetic unresolved reference marker",
                    )
                ],
            )
        return ResolveResult(True, 0, [])

    def typecheck(self, text: str) -> TypecheckResult:
        if "type_error" in normalize_ws(text):
            return TypecheckResult(
                False,
                1,
                [
                    ErrorDetail(
                        stage="typecheck",
                        code="TYPECHECK_ERROR",
                        message="Synthetic type error marker",
                    )
                ],
            )
        return TypecheckResult(True, 0, [])


class MontiCoreStubAdapter(PilotStubAdapter):
    name = "monticore-stub"

    def fingerprint(self) -> str:
        return "monticore-stub@0.6.0"

    def parse(self, text: str) -> ParseResult:
        normalized = normalize_ws(text)
        if "parser_disagreement" in normalized:
            return ParseResult(
                False,
                [
                    ErrorDetail(
                        stage="parse",
                        code="PARSE_SECONDARY_DISAGREEMENT",
                        message="Synthetic secondary parser disagreement marker",
                    )
                ],
            )

        result = super().parse(text)
        if result.ok and "summary_disagreement" in normalized:
            changed = list(result.element_summary)
            changed.append(ElementSummary(type="part", qualified_name="monticore.synthetic"))
            return ParseResult(True, [], changed)
        return result

    def parser_agrees(self, text: str, pilot: ValidatorAdapter) -> bool:
        pilot_result = pilot.parse(text)
        monticore_result = self.parse(text)
        return (
            pilot_result.ok == monticore_result.ok
            and element_summary_counter(pilot_result.element_summary)
            == element_summary_counter(monticore_result.element_summary)
        )
