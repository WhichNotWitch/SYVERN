from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.error import URLError
from urllib.request import Request, urlopen


FormalTool = Literal["imandra", "gamma", "nuxmv"]
FormalStatus = Literal["proved", "failed", "unknown", "timeout", "error"]
SUPPORTED_FORMAL_TOOLS: frozenset[str] = frozenset({"imandra", "gamma", "nuxmv"})


@dataclass(frozen=True)
class FormalResult:
    tool: FormalTool
    status: FormalStatus
    properties_checked: int = 0
    conclusions: list[str] = field(default_factory=list)
    counterexamples: list[str] = field(default_factory=list)


class FormalAdapter:
    def __init__(self, tool: str, endpoint: str, version: str, timeout_s: float) -> None:
        normalized_tool = tool.strip().lower()
        if normalized_tool not in SUPPORTED_FORMAL_TOOLS:
            raise ValueError(f"unsupported formal tool: {tool}")
        self.tool: FormalTool = normalized_tool  # type: ignore[assignment]
        self.endpoint = endpoint
        self.version = version
        self.timeout_s = timeout_s

    def analyze(self, text: str, properties: list[str] | None = None) -> FormalResult:
        try:
            payload = self._post(text, properties or [])
            return FormalResult(
                tool=self.tool,
                status=self._status(payload.get("status")),
                properties_checked=int(payload.get("properties_checked", 0)),
                conclusions=self._strings(payload.get("conclusions", [])),
                counterexamples=self._strings(payload.get("counterexamples", [])),
            )
        except TimeoutError as exc:
            return self._timeout_result(exc)
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return self._timeout_result(exc)
            return self._error_result(exc)
        except Exception as exc:
            return self._error_result(exc)

    def fingerprint(self) -> str:
        return f"formal-{self.tool}@{self.version}"

    def _post(self, text: str, properties: list[str]) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/analyze",
            data=json.dumps({"text": text, "properties": properties}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("formal backend returned a non-object payload")
        return payload

    def _status(self, value: Any) -> FormalStatus:
        if value in {"proved", "failed", "unknown", "timeout", "error"}:
            return value
        return "unknown"

    def _strings(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]

    def _timeout_result(self, exc: Exception) -> FormalResult:
        return FormalResult(
            tool=self.tool,
            status="timeout",
            conclusions=[f"{self.tool} formal analysis timed out: {exc}"],
        )

    def _error_result(self, exc: Exception) -> FormalResult:
        return FormalResult(
            tool=self.tool,
            status="error",
            conclusions=[f"{self.tool} formal analysis failed: {exc}"],
        )
