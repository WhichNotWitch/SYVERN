from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from syvern.normalization import normalize_ws


class LLMPerturbationAdapter:
    def __init__(self, endpoint: str, model: str, rubric_version: str, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.model = model
        self.rubric_version = rubric_version
        self.timeout_s = timeout_s

    def generate(self, spec: str, n: int) -> list[str]:
        try:
            payload = self._post(spec, n)
            return self._perturbations(payload.get("perturbations"), n)
        except Exception:
            return []

    def fingerprint(self) -> str:
        return f"perturbation-llm@{self.model}+rubric@{self.rubric_version}"

    def _post(self, spec: str, n: int) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint.rstrip('/')}/perturb",
            data=json.dumps(
                {
                    "spec": spec,
                    "n": n,
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
            raise ValueError("perturbation backend returned a non-object payload")
        return payload

    def _perturbations(self, raw: Any, n: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        variants: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            normalized = normalize_ws(item)
            if not normalized or normalized in seen:
                continue
            variants.append(normalized)
            seen.add(normalized)
            if len(variants) >= n:
                break
        return variants
