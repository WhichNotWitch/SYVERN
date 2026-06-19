from __future__ import annotations

from syvern.adapters.stub import extract_element_summary
from syvern.settings import SyvernSettings
from syvern.structural import match_structural


def _reference_from_original_output(original_text: str) -> dict[str, list[dict[str, str]]] | None:
    elements = extract_element_summary(original_text)
    if not elements:
        return None
    return {
        "elements": [
            {"type": element.type, "qualified_name": element.qualified_name}
            for element in elements
        ]
    }


def evaluate_ipt(
    *,
    original_text: str,
    perturbations: list[str] | None,
    settings: SyvernSettings,
) -> bool | None:
    reference = _reference_from_original_output(original_text)
    if not perturbations or reference is None:
        return None

    for perturbation in perturbations:
        summary = match_structural(
            extract_element_summary(perturbation),
            reference,
            settings,
        )
        if summary.f1 < settings.ipt_threshold:
            return False
    return True
