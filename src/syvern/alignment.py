from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from syvern.adapters.base import ValidatorAdapter


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass(frozen=True)
class AlignmentCase:
    case_id: str
    text: str
    parse_ok: bool
    unresolved_refs: int
    type_errors: int
    category: str = "unspecified"
    # None = element set not labelled (skipped by element accuracy);
    # () = labelled empty (e.g. syntax errors yield no elements).
    expected_elements: tuple[tuple[str, str], ...] | None = None


@dataclass(frozen=True)
class AlignmentFailure:
    case_id: str
    stage: str
    expected: str
    actual: str


@dataclass(frozen=True)
class AlignmentSummary:
    adapter_name: str
    adapter_fingerprint: str
    total: int
    parse_accuracy: float
    resolve_accuracy: float
    typecheck_accuracy: float
    element_accuracy: float
    element_labelled: int
    overall_accuracy: float
    category_counts: dict[str, int]
    failures: list[AlignmentFailure] = field(default_factory=list)


def _parse_expected_elements(raw: object) -> tuple[tuple[str, str], ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("expected_elements must be a list")
    elements: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict) or "type" not in item or "qualified_name" not in item:
            raise ValueError("expected_elements items need 'type' and 'qualified_name'")
        elements.append((_normalize(str(item["type"])), _normalize(str(item["qualified_name"]))))
    return tuple(elements)


def load_alignment_cases(path: str | Path) -> list[AlignmentCase]:
    dataset_path = Path(path)
    cases: list[AlignmentCase] = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        try:
            cases.append(
                AlignmentCase(
                    case_id=str(payload["case_id"]),
                    text=str(payload["text"]),
                    parse_ok=bool(payload["parse_ok"]),
                    unresolved_refs=int(payload["unresolved_refs"]),
                    type_errors=int(payload["type_errors"]),
                    category=str(payload.get("category", "unspecified")).strip() or "unspecified",
                    expected_elements=_parse_expected_elements(payload.get("expected_elements")),
                )
            )
        except KeyError as exc:
            missing = exc.args[0]
            raise ValueError(f"{dataset_path}:{line_number} missing required field {missing}") from exc
    if not cases:
        raise ValueError(f"{dataset_path} does not contain any alignment cases")
    return cases


def calibrated_case_payloads(
    adapter: ValidatorAdapter,
    cases: Iterable[AlignmentCase],
) -> list[dict[str, object]]:
    """Re-label cases with the adapter's *actual* output.

    Used by ``syvern align --emit-calibrated`` to turn manual corpus calibration
    into "run once, review the diff": each case keeps its id / category / text but
    its ``parse_ok`` / ``unresolved_refs`` / ``type_errors`` / ``expected_elements``
    become whatever the adapter currently produces. A human reviews the emitted
    corpus before adopting it as ground truth.
    """
    payloads: list[dict[str, object]] = []
    for case in cases:
        parse_result = adapter.parse(case.text)
        resolve_result = adapter.resolve(case.text)
        typecheck_result = adapter.typecheck(case.text)
        payloads.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "text": case.text,
                "parse_ok": parse_result.ok,
                "unresolved_refs": resolve_result.unresolved_refs,
                "type_errors": typecheck_result.type_errors,
                "expected_elements": [
                    {"type": element.type, "qualified_name": element.qualified_name}
                    for element in parse_result.element_summary
                ],
            }
        )
    return payloads


def run_adapter_alignment(
    adapter: ValidatorAdapter,
    cases: Iterable[AlignmentCase],
) -> AlignmentSummary:
    case_list = list(cases)
    if not case_list:
        raise ValueError("alignment cases must not be empty")

    parse_matches = 0
    resolve_matches = 0
    typecheck_matches = 0
    element_matches = 0
    element_labelled = 0
    overall_matches = 0
    failures: list[AlignmentFailure] = []

    for case in case_list:
        parse_result = adapter.parse(case.text)
        resolve_result = adapter.resolve(case.text)
        typecheck_result = adapter.typecheck(case.text)

        case_failures = []
        if parse_result.ok == case.parse_ok:
            parse_matches += 1
        else:
            case_failures.append(
                AlignmentFailure(case.case_id, "parse", str(case.parse_ok), str(parse_result.ok))
            )

        if resolve_result.unresolved_refs == case.unresolved_refs:
            resolve_matches += 1
        else:
            case_failures.append(
                AlignmentFailure(
                    case.case_id,
                    "resolve",
                    str(case.unresolved_refs),
                    str(resolve_result.unresolved_refs),
                )
            )

        if typecheck_result.type_errors == case.type_errors:
            typecheck_matches += 1
        else:
            case_failures.append(
                AlignmentFailure(
                    case.case_id,
                    "typecheck",
                    str(case.type_errors),
                    str(typecheck_result.type_errors),
                )
            )

        if case.expected_elements is not None:
            element_labelled += 1
            expected = Counter(case.expected_elements)
            actual = Counter(
                (element.type, element.qualified_name) for element in parse_result.element_summary
            )
            if expected == actual:
                element_matches += 1
            else:
                case_failures.append(
                    AlignmentFailure(
                        case.case_id,
                        "elements",
                        str(sorted(expected.elements())),
                        str(sorted(actual.elements())),
                    )
                )

        if not case_failures:
            overall_matches += 1
        failures.extend(case_failures)

    total = len(case_list)
    return AlignmentSummary(
        adapter_name=adapter.name,
        adapter_fingerprint=adapter.fingerprint(),
        total=total,
        parse_accuracy=parse_matches / total,
        resolve_accuracy=resolve_matches / total,
        typecheck_accuracy=typecheck_matches / total,
        element_accuracy=element_matches / element_labelled if element_labelled else 1.0,
        element_labelled=element_labelled,
        overall_accuracy=overall_matches / total,
        category_counts=dict(sorted(Counter(case.category for case in case_list).items())),
        failures=failures,
    )
