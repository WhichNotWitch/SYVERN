from __future__ import annotations

from typing import Any

from syvern.adapters.stub import extract_element_summary
from syvern.settings import SyvernSettings
from syvern.structural import match_structural


def evaluate_ipt(
    *,
    perturbations: list[str] | None,
    reference: dict[str, Any] | None,
    settings: SyvernSettings,
) -> bool | None:
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
