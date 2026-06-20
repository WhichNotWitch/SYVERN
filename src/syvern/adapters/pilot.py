from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult
from syvern.models import ElementSummary, ErrorDetail


class PilotBackendError(RuntimeError):
    """The Pilot backend is unreachable or returned a transport-level error.

    Distinct from a *validation* failure (HTTP 200 with ``ok=false``), which
    flows through the normal stage gates. Callers should treat this as backend
    unavailability (circuit-break / 503), not as a model defect — otherwise a
    transient network blip is mis-scored as a failed model and gets reward 0.
    """


@dataclass(frozen=True)
class _Analysis:
    parse: ParseResult
    resolve: ResolveResult
    typecheck: TypecheckResult


class PilotAdapter:
    """HTTP client for the SYVERN Pilot service (services/pilot-server).

    One ``POST /validate`` per text feeds all three T0 stages (parse / resolve /
    typecheck) plus the element set, instead of three separate round trips. The
    result is memoized per text in thread-local state: the pipeline calls
    ``parse`` then ``resolve`` then ``typecheck`` with the same text on one
    thread, so only the first call hits the network. Thread-local keying avoids
    cross-request contamination when the adapter instance is shared.
    """

    name = "pilot"

    def __init__(self, endpoint: str, version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.version = version
        self.timeout_s = timeout_s
        self._local = threading.local()
        self._version_lock = threading.Lock()
        self._resolved_version: str | None = None

    def parse(self, text: str) -> ParseResult:
        return self._analyze(text).parse

    def resolve(self, text: str) -> ResolveResult:
        return self._analyze(text).resolve

    def typecheck(self, text: str) -> TypecheckResult:
        return self._analyze(text).typecheck

    def fingerprint(self) -> str:
        return f"pilot@{self._backend_version()}"

    def _analyze(self, text: str) -> _Analysis:
        if getattr(self._local, "text", None) != text:
            self._local.analysis = self._request_analysis(text)
            self._local.text = text
        return self._local.analysis

    def _request_analysis(self, text: str) -> _Analysis:
        payload = self._post("validate", {"text": text})
        parse_obj = _as_dict(payload.get("parse"))
        resolve_obj = _as_dict(payload.get("resolve"))
        typecheck_obj = _as_dict(payload.get("typecheck"))
        elements = payload.get("elements", [])
        return _Analysis(
            parse=ParseResult(
                ok=bool(parse_obj.get("ok", False)),
                errors=self._errors(parse_obj.get("errors", []), "parse"),
                element_summary=[
                    ElementSummary(
                        type=str(item.get("type", "")),
                        qualified_name=str(item.get("qualified_name", "")),
                    )
                    for item in elements
                    if isinstance(item, dict)
                ],
            ),
            resolve=ResolveResult(
                ok=bool(resolve_obj.get("ok", False)),
                unresolved_refs=int(resolve_obj.get("unresolved_refs", 0)),
                errors=self._errors(resolve_obj.get("errors", []), "resolve"),
            ),
            typecheck=TypecheckResult(
                ok=bool(typecheck_obj.get("ok", False)),
                type_errors=int(typecheck_obj.get("type_errors", 0)),
                errors=self._errors(typecheck_obj.get("errors", []), "typecheck"),
            ),
        )

    def _backend_version(self) -> str:
        if self._resolved_version is None:
            with self._version_lock:
                if self._resolved_version is None:
                    self._resolved_version = self._handshake_version()
        return self._resolved_version

    def _handshake_version(self) -> str:
        try:
            payload = self._get("version")
        except PilotBackendError:
            # /version unavailable: fall back to the operator-declared version so
            # startup is not blocked by a transient outage.
            return self.version
        return str(payload.get("pilot_version") or self.version)

    def _post(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/{operation}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request)

    def _get(self, operation: str) -> dict[str, Any]:
        request = Request(f"{self.endpoint.rstrip('/')}/{operation}", method="GET")
        return self._send(request)

    def _send(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as exc:
            raise PilotBackendError(f"Pilot backend request failed: {exc}") from exc

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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
