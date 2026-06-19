from __future__ import annotations

import json
from urllib.request import Request, urlopen

from syvern.models import ElementSummary


class LLMStructuralMatcherAdapter:
    def __init__(self, endpoint: str, model: str, rubric_version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.model = model
        self.rubric_version = rubric_version
        self.timeout_s = timeout_s

    def match(self, generated: ElementSummary, reference: ElementSummary) -> bool:
        try:
            payload = self._post(generated, reference)
            return bool(payload.get("match", False))
        except Exception:
            return False

    def fingerprint(self) -> str:
        return f"structural-llm@{self.model}+rubric@{self.rubric_version}"

    def _post(self, generated: ElementSummary, reference: ElementSummary) -> dict:
        request = Request(
            f"{self.endpoint.rstrip('/')}/structural_match",
            data=json.dumps(
                {
                    "generated": generated.model_dump(),
                    "reference": reference.model_dump(),
                    "model": self.model,
                    "rubric_version": self.rubric_version,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("structural matcher returned a non-object payload")
        return payload
