from __future__ import annotations

import re
from typing import Any

from syvern.coverage.base import CoverageEvaluator
from syvern.coverage.schema import CoverageItem, CoverageReport


_COMMON_TITLE_WORDS = {
    "A",
    "An",
    "And",
    "If",
    "In",
    "On",
    "The",
    "Then",
    "When",
}


class SimpleCoverageEvaluator(CoverageEvaluator):
    def __init__(self, min_coverage: float = 0.6) -> None:
        self.min_coverage = min_coverage

    def evaluate(
        self,
        requirement_text: str,
        sysml_text: str,
        *,
        sample_id: str | None = None,
        metadata: dict | None = None,
    ) -> CoverageReport:
        metadata = metadata or {}
        coverage_spec = metadata.get("coverage_spec") or {}
        if not isinstance(coverage_spec, dict):
            coverage_spec = {}
        required = _string_list(coverage_spec.get("required")) or self._extract_required_items(
            requirement_text
        )
        aliases = coverage_spec.get("aliases")
        alias_map = aliases if isinstance(aliases, dict) else {}
        normalized_sysml = self._normalize(sysml_text)
        matched_items: list[CoverageItem] = []
        missing_items: list[str] = []

        for item in required:
            evidence = []
            normalized_item = self._normalize(item)
            if normalized_item and normalized_item in normalized_sysml:
                evidence.append(f"direct match: {item}")
            for alias, targets in alias_map.items():
                if not isinstance(alias, str) or item not in _string_list(targets):
                    continue
                if alias.lower() in requirement_text.lower() and normalized_item in normalized_sysml:
                    evidence.append(f"alias match: {alias} -> {item}")
            matched = bool(evidence)
            matched_items.append(CoverageItem(name=item, matched=matched, evidence=evidence))
            if not matched:
                missing_items.append(item)

        score = (
            sum(1 for item in matched_items if item.matched) / len(matched_items)
            if matched_items
            else 0.0
        )
        return CoverageReport(
            sample_id=sample_id,
            backend="simple",
            score=score,
            passed=score >= self.min_coverage,
            required_items=matched_items,
            missing_items=missing_items,
            evidence_type="keyword_alias_match",
        )

    def _normalize(self, text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "", text).lower()

    def _extract_required_items(self, requirement_text: str) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for token in re.findall(r"[A-Z][A-Za-z0-9_]+", requirement_text):
            if token in _COMMON_TITLE_WORDS:
                continue
            if token not in seen:
                seen.add(token)
                items.append(token)
        return items


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
