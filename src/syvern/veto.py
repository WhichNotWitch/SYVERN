from __future__ import annotations

from syvern.adapters.stub import extract_element_summary
from syvern.models import VetoSummary, Violation
from syvern.normalization import token_count
from syvern.settings import SyvernSettings


def evaluate_veto(
    *,
    text: str,
    settings: SyvernSettings,
    semantic_path_passed: bool,
    parser_agreement: bool,
    violations: list[Violation],
) -> VetoSummary:
    if not parser_agreement:
        return VetoSummary(triggered=True, reason="parser_disagreement")

    if any(v.category == "anti_gaming" and v.severity == "error" for v in violations):
        return VetoSummary(triggered=True, reason="anti_gaming_rule")

    if semantic_path_passed:
        if token_count(text) < settings.min_tokens:
            return VetoSummary(triggered=True, reason="degenerate_output")
        if len(extract_element_summary(text)) < settings.min_elements:
            return VetoSummary(triggered=True, reason="degenerate_output")

    return VetoSummary(triggered=False, reason=None)
