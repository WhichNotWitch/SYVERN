from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from syvern.models import ElementSummary, StructuralSummary
from syvern.settings import SyvernSettings


ElementKey = tuple[str, str]


@dataclass(frozen=True)
class ReferenceModel:
    elements: list[ElementSummary] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    coverage: dict[str, set[str]] = field(default_factory=dict)


def normalize_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def parse_reference(reference: dict[str, Any] | None) -> ReferenceModel:
    if not isinstance(reference, dict):
        return ReferenceModel()

    elements: list[ElementSummary] = []
    raw_elements = reference.get("elements", [])
    if isinstance(raw_elements, list):
        for raw_element in raw_elements:
            if not isinstance(raw_element, dict):
                continue
            try:
                elements.append(ElementSummary.model_validate(raw_element))
            except ValidationError:
                continue

    requirements: list[str] = []
    raw_requirements = reference.get("requirements", [])
    if isinstance(raw_requirements, list):
        for raw_requirement in raw_requirements:
            normalized = normalize_label(raw_requirement)
            if normalized is not None:
                requirements.append(normalized)

    coverage: dict[str, set[str]] = {}
    raw_coverage = reference.get("coverage", {})
    if isinstance(raw_coverage, dict):
        for raw_requirement, raw_targets in raw_coverage.items():
            requirement = normalize_label(raw_requirement)
            if requirement is None or not isinstance(raw_targets, list):
                continue
            targets = {
                target
                for target in (normalize_label(raw_target) for raw_target in raw_targets)
                if target is not None
            }
            coverage[requirement] = targets

    return ReferenceModel(elements=elements, requirements=requirements, coverage=coverage)


def element_key(element: ElementSummary) -> ElementKey:
    return (element.type, element.qualified_name)


def element_counter(elements: list[ElementSummary]) -> Counter[ElementKey]:
    return Counter(element_key(element) for element in elements)


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def match_structural(
    *,
    generated: list[ElementSummary],
    reference: dict[str, Any] | None,
    settings: SyvernSettings,
) -> StructuralSummary:
    reference_model = parse_reference(reference)
    generated_counter = element_counter(generated)
    reference_counter = element_counter(reference_model.elements)
    matched_counter = generated_counter & reference_counter
    matched = sum(matched_counter.values())

    generated_count = len(generated)
    reference_count = len(reference_model.elements)
    precision = matched / generated_count if generated_count else 0.0
    recall = matched / reference_count if reference_count else 0.0
    matched_names = {
        qualified_name
        for (_element_type, qualified_name), count in matched_counter.items()
        if count > 0
    }
    reference_names = {element.qualified_name for element in reference_model.elements}
    covered_requirements = 0
    for requirement in reference_model.requirements:
        targets = reference_model.coverage.get(requirement, set())
        valid_targets = targets & reference_names
        if valid_targets & matched_names:
            covered_requirements += 1
    requirement_coverage = (
        covered_requirements / len(reference_model.requirements)
        if reference_model.requirements
        else 0.0
    )

    return StructuralSummary(
        evaluated=True,
        precision=precision,
        recall=recall,
        f1=f1_score(precision, recall),
        requirement_coverage=requirement_coverage,
        ged_accuracy=None,
        hallucinated_elements=generated_count - matched,
        matching_policy_id=settings.matching_policy_id,
    )
