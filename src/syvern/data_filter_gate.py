from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Any

from syvern.pipeline import ValidationPipeline


@dataclass(frozen=True)
class DataFilterGateFailure:
    case_id: str
    expected: bool
    actual: bool
    reason: str | None
    parse_ok: bool
    resolve_ok: bool
    typecheck_ok: bool
    t0_pass: bool


@dataclass(frozen=True)
class DataFilterGateSummary:
    total: int
    matches: int
    accuracy: float
    failures: list[DataFilterGateFailure] = field(default_factory=list)


def run_data_filter_gate_check(
    pipeline: ValidationPipeline,
    records: Iterable[Mapping[str, Any]],
) -> DataFilterGateSummary:
    total = 0
    matches = 0
    failures: list[DataFilterGateFailure] = []

    for index, record in enumerate(records, start=1):
        case_id = str(record.get("case_id") or f"case_{index}")
        text = record.get("text")
        keep_expected = record.get("keep_expected")
        if not isinstance(text, str) or not isinstance(keep_expected, bool):
            raise ValueError(f"{case_id}: records need string text and bool keep_expected")

        response = pipeline.validate(text, mode="data_filter")
        actual = bool(response.meta.data_filter_pass)
        total += 1
        if actual == keep_expected:
            matches += 1
            continue
        failures.append(
            DataFilterGateFailure(
                case_id=case_id,
                expected=keep_expected,
                actual=actual,
                reason=response.meta.data_filter_reason,
                parse_ok=response.stage.parse.ok,
                resolve_ok=response.stage.resolve.ok,
                typecheck_ok=response.stage.typecheck.ok,
                t0_pass=response.tier_summary.t0_pass,
            )
        )

    return DataFilterGateSummary(
        total=total,
        matches=matches,
        accuracy=(matches / total) if total else 0.0,
        failures=failures,
    )
