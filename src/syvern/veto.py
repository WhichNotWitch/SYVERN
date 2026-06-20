from __future__ import annotations

from syvern.models import ElementSummary, VetoSummary, Violation
from syvern.normalization import token_count
from syvern.settings import SyvernSettings


def evaluate_veto(
    *,
    text: str,
    elements: list[ElementSummary],
    settings: SyvernSettings,
    semantic_path_passed: bool,
    parser_agreement: bool | None,
    violations: list[Violation],
) -> VetoSummary:
    if parser_agreement is False:
        return VetoSummary(triggered=True, reason="parser_disagreement")

    if any(v.category == "anti_gaming" and v.severity == "error" for v in violations):
        return VetoSummary(triggered=True, reason="anti_gaming_rule")

    if semantic_path_passed:
        if token_count(text) < settings.min_tokens:
            return VetoSummary(triggered=True, reason="degenerate_output")
        # NOTE (Bug2): we deliberately do NOT veto on an empty *curated* element
        # set. `elements` is the structural-matching subset (part/attribute/…)
        # and omits valid constructs like `metadata def`, `enum def`, and
        # anonymous `action {}` bodies. A model that fully parses/resolves/
        # typechecks against the standard library is non-degenerate by the
        # authoritative L0's own verdict; the curated subset being empty is a
        # scoping artifact, not evidence of emptiness. See
        # doc/syvern_bug2_element_degeneracy_fix.md.

    return VetoSummary(triggered=False, reason=None)
