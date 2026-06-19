from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult
from syvern.models import ElementSummary, ErrorDetail


class PilotAdapter:
    name = "pilot"

    def __init__(self, endpoint: str, version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.version = version
        self.timeout_s = timeout_s

    def parse(self, text: str) -> ParseResult:
        try:
            payload = self._post("parse", text)
            return ParseResult(
                ok=bool(payload.get("ok", False)),
                errors=self._errors(payload.get("errors", []), "parse"),
                element_summary=[
                    ElementSummary(
                        type=str(item.get("type", "")),
                        qualified_name=str(item.get("qualified_name", "")),
                    )
                    for item in payload.get("elements", [])
                ],
            )
        except Exception as exc:
            return ParseResult(ok=False, errors=[self._backend_error("parse", exc)])

    def resolve(self, text: str) -> ResolveResult:
        try:
            payload = self._post("resolve", text)
            return ResolveResult(
                ok=bool(payload.get("ok", False)),
                unresolved_refs=int(payload.get("unresolved_refs", 0)),
                errors=self._errors(payload.get("errors", []), "resolve"),
            )
        except Exception as exc:
            return ResolveResult(ok=False, errors=[self._backend_error("resolve", exc)])

    def typecheck(self, text: str) -> TypecheckResult:
        try:
            payload = self._post("typecheck", text)
            return TypecheckResult(
                ok=bool(payload.get("ok", False)),
                type_errors=int(payload.get("type_errors", 0)),
                errors=self._errors(payload.get("errors", []), "typecheck"),
            )
        except Exception as exc:
            return TypecheckResult(ok=False, errors=[self._backend_error("typecheck", exc)])

    def fingerprint(self) -> str:
        return f"pilot@{self.version}"

    def _post(self, operation: str, text: str) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/{operation}",
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def _errors(self, errors: Any, stage: str) -> list[ErrorDetail]:
        if not isinstance(errors, list):
            return [
                ErrorDetail(
                    stage=stage,
                    code=f"PILOT_{stage.upper()}_ERROR",
                    message="Pilot backend returned a non-list error payload",
                )
            ]
        return [self._error_detail(error, stage) for error in errors]

    def _error_detail(self, error: Any, stage: str) -> ErrorDetail:
        if not isinstance(error, dict):
            return ErrorDetail(
                stage=stage,
                code=f"PILOT_{stage.upper()}_ERROR",
                message=str(error),
            )
        code = str(error.get("code") or f"PILOT_{stage.upper()}_ERROR")
        return ErrorDetail(
            stage=stage,
            code=code,
            message=str(error.get("message") or code),
            location=error.get("location"),
        )

    def _backend_error(self, stage: str, exc: Exception) -> ErrorDetail:
        return ErrorDetail(
            stage=stage,
            code="PILOT_BACKEND_ERROR",
            message=f"Pilot backend request failed: {exc}",
        )
