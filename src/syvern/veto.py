from __future__ import annotations

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

    if semantic_path_passed and token_count(text) < settings.min_tokens:
        return VetoSummary(triggered=True, reason="degenerate_output")

    if any(v.category == "anti_gaming" and v.severity == "error" for v in violations):
        return VetoSummary(triggered=True, reason="anti_gaming_rule")

    return VetoSummary(triggered=False, reason=None)
