from __future__ import annotations

from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult, ValidatorAdapter
from syvern.models import ErrorDetail
from syvern.normalization import normalize_ws


class PilotStubAdapter:
    name = "pilot-stub"

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
        return ParseResult(True, [])

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

    def parser_agrees(self, text: str, pilot: ValidatorAdapter) -> bool:
        if "parser_disagreement" in normalize_ws(text):
            return False
        return self.parse(text).ok == pilot.parse(text).ok
