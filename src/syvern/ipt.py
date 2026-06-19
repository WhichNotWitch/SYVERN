from __future__ import annotations

from syvern.models import ElementSummary
from syvern.settings import SyvernSettings
from syvern.structural import match_structural


def _reference_from_original_elements(
    original_elements: list[ElementSummary],
) -> dict[str, list[dict[str, str]]] | None:
    if not original_elements:
        return None
    return {
        "elements": [
            {"type": element.type, "qualified_name": element.qualified_name}
            for element in original_elements
        ]
    }


def evaluate_ipt(
    *,
    original_elements: list[ElementSummary],
    perturbation_element_sets: list[list[ElementSummary]] | None,
    settings: SyvernSettings,
) -> bool | None:
    reference = _reference_from_original_elements(original_elements)
    if not perturbation_element_sets or reference is None:
        return None

    for perturbation_elements in perturbation_element_sets:
        summary = match_structural(
            perturbation_elements,
            reference,
            settings,
        )
        if summary.f1 < settings.ipt_threshold:
            return False
    return True
