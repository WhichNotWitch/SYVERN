from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from syvern.models import IntentSummary


class LLMIntentJudgeAdapter:
    def __init__(self, endpoint: str, model: str, rubric_version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.model = model
        self.rubric_version = rubric_version
        self.timeout_s = timeout_s

    def judge(self, text: str, intent_reference: dict) -> IntentSummary:
        try:
            payload = self._post(text, intent_reference)
            if not payload.get("evaluated", False):
                return IntentSummary()
            return IntentSummary(
                evaluated=True,
                score=self._score(payload.get("score")),
                source="llm_judge",
            )
        except Exception:
            return IntentSummary()

    def fingerprint(self) -> str:
        return f"intent-llm@{self.model}+rubric@{self.rubric_version}"

    def _post(self, text: str, intent_reference: dict) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/judge",
            data=json.dumps(
                {
                    "text": text,
                    "intent_reference": intent_reference,
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
            raise ValueError("intent judge returned a non-object payload")
        return payload

    def _score(self, value: Any) -> float:
        return max(0.0, min(5.0, float(value)))
