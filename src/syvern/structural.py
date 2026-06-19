from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any

from pydantic import ValidationError

from syvern.models import ElementSummary, StructuralSummary
from syvern.settings import SyvernSettings


ElementKey = tuple[str, str]

GENERATED_SUFFIX_PATTERN = re.compile(
    r"(?:[-_\s.]?(?:generated|synthetic|auto|copy|candidate|output|gen|model))+$"
)
TRAILING_NUMBER_PATTERN = re.compile(r"[-_\s.]?\d+$")


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


def normalized_structural_name(qualified_name: str) -> str:
    leaf_name = qualified_name.rsplit(".", 1)[-1]
    normalized = " ".join(leaf_name.strip().lower().split())
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = GENERATED_SUFFIX_PATTERN.sub("", normalized)
        normalized = TRAILING_NUMBER_PATTERN.sub("", normalized)
        normalized = normalized.strip(" -_.")
    return normalized


def edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current_row = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current_row[right_index - 1] + 1
            delete_cost = previous_row[right_index] + 1
            replace_cost = previous_row[right_index - 1] + (0 if left_char == right_char else 1)
            current_row.append(min(insert_cost, delete_cost, replace_cost))
        previous_row = current_row
    return previous_row[-1]


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def ged_accuracy(matched: int, generated_count: int, reference_count: int) -> float:
    graph_size = max(generated_count, reference_count)
    if graph_size == 0:
        return 0.0
    generated_unmatched = generated_count - matched
    reference_unmatched = reference_count - matched
    edit_operations = max(generated_unmatched, reference_unmatched)
    return max(0.0, 1.0 - (edit_operations / graph_size))


def _match_indices(
    generated: list[ElementSummary],
    reference: list[ElementSummary],
    generated_matched: set[int],
    reference_matched: set[int],
    predicate: Any,
) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    for generated_index, generated_element in enumerate(generated):
        if generated_index in generated_matched:
            continue
        for reference_index, reference_element in enumerate(reference):
            if reference_index in reference_matched:
                continue
            if predicate(generated_element, reference_element):
                generated_matched.add(generated_index)
                reference_matched.add(reference_index)
                matches.append((generated_index, reference_index))
                break
    return matches


def match_structural(
    generated: list[ElementSummary],
    reference: dict[str, Any] | None,
    settings: SyvernSettings,
    soft_matcher: Any | None = None,
) -> StructuralSummary:
    reference_model = parse_reference(reference)
    generated_matched: set[int] = set()
    reference_matched: set[int] = set()

    exact_matches = _match_indices(
        generated,
        reference_model.elements,
        generated_matched,
        reference_matched,
        lambda generated_element, reference_element: element_key(generated_element)
        == element_key(reference_element),
    )
    normalized_matches = _match_indices(
        generated,
        reference_model.elements,
        generated_matched,
        reference_matched,
        lambda generated_element, reference_element: (
            generated_element.type == reference_element.type
            and normalized_structural_name(generated_element.qualified_name)
            == normalized_structural_name(reference_element.qualified_name)
        ),
    )
    fuzzy_matches = _match_indices(
        generated,
        reference_model.elements,
        generated_matched,
        reference_matched,
        lambda generated_element, reference_element: (
            generated_element.type == reference_element.type
            and edit_distance(
                normalized_structural_name(generated_element.qualified_name),
                normalized_structural_name(reference_element.qualified_name),
            )
            <= settings.fuzzy_threshold
        ),
    )
    soft_matches: list[tuple[int, int]] = []
    if soft_matcher is not None:
        soft_matches = _match_indices(
            generated,
            reference_model.elements,
            generated_matched,
            reference_matched,
            lambda generated_element, reference_element: (
                generated_element.type == reference_element.type
                and bool(soft_matcher.match(generated_element, reference_element))
            ),
        )
    matched_reference_indices = {
        reference_index
        for _generated_index, reference_index in [
            *exact_matches,
            *normalized_matches,
            *fuzzy_matches,
            *soft_matches,
        ]
    }
    matched = len(matched_reference_indices)

    generated_count = len(generated)
    reference_count = len(reference_model.elements)
    precision = matched / generated_count if generated_count else 0.0
    recall = matched / reference_count if reference_count else 0.0
    matched_names = {
        reference_model.elements[reference_index].qualified_name
        for reference_index in matched_reference_indices
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
        ged_accuracy=ged_accuracy(matched, generated_count, reference_count),
        hallucinated_elements=generated_count - matched,
        exact_matched=len(exact_matches),
        normalized_matched=len(normalized_matches),
        fuzzy_matched=len(fuzzy_matches),
        soft_matched=len(soft_matches),
        matching_policy_id=settings.matching_policy_id,
    )
