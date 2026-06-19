from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from syvern.adapters.base import ParseResult, ValidatorAdapter, element_summary_counter
from syvern.models import ElementSummary, ErrorDetail


class MontiCoreAdapter:
    name = "monticore"

    def __init__(self, endpoint: str, version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.version = version
        self.timeout_s = timeout_s

    def parse(self, text: str) -> ParseResult:
        try:
            payload = self._post("parse", text)
            return ParseResult(
                ok=bool(payload.get("ok", False)),
                errors=self._errors(payload.get("errors", [])),
                element_summary=[
                    ElementSummary(
                        type=str(item.get("type", "")),
                        qualified_name=str(item.get("qualified_name", "")),
                    )
                    for item in payload.get("elements", [])
                ],
            )
        except Exception as exc:
            return ParseResult(ok=False, errors=[self._backend_error(exc)])

    def parser_agrees(self, text: str, pilot: ValidatorAdapter) -> bool:
        pilot_result = pilot.parse(text)
        monticore_result = self.parse(text)
        return (
            pilot_result.ok == monticore_result.ok
            and element_summary_counter(pilot_result.element_summary)
            == element_summary_counter(monticore_result.element_summary)
        )

    def fingerprint(self) -> str:
        return f"monticore@{self.version}"

    def _post(self, operation: str, text: str) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/{operation}",
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def _errors(self, errors: Any) -> list[ErrorDetail]:
        if not isinstance(errors, list):
            return [
                ErrorDetail(
                    stage="parse",
                    code="MONTICORE_PARSE_ERROR",
                    message="MontiCore backend returned a non-list error payload",
                )
            ]
        return [self._error_detail(error) for error in errors]

    def _error_detail(self, error: Any) -> ErrorDetail:
        if not isinstance(error, dict):
            return ErrorDetail(stage="parse", code="MONTICORE_PARSE_ERROR", message=str(error))
        code = str(error.get("code") or "MONTICORE_PARSE_ERROR")
        return ErrorDetail(
            stage="parse",
            code=code,
            message=str(error.get("message") or code),
            location=error.get("location"),
        )

    def _backend_error(self, exc: Exception) -> ErrorDetail:
        return ErrorDetail(
            stage="parse",
            code="MONTICORE_BACKEND_ERROR",
            message=f"MontiCore backend request failed: {exc}",
        )
