"""Legacy SFT data-filter wrapper kept for the existing ``syvern filter`` CLI."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from syvern.pipeline import ValidationPipeline

REASON_MALFORMED = "malformed_input"
REASON_MISSING_TEXT = "missing_text"


@dataclass
class SftFilterSummary:
    read: int = 0
    evaluated: int = 0
    passed: int = 0
    dropped: int = 0
    skipped: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def keep_ratio(self) -> float:
        return self.passed / self.read if self.read else 0.0


@dataclass
class SftFilterResult:
    summary: SftFilterSummary
    kept: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


def run_sft_filter(
    pipeline: ValidationPipeline,
    lines: Iterable[str],
    *,
    text_field: str = "text",
) -> SftFilterResult:
    summary = SftFilterSummary()
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        summary.read += 1

        record = _load_record(line)
        if record is None:
            _record_skip(summary, rejected, {"_raw": line}, REASON_MALFORMED)
            continue

        text = record.get(text_field)
        if not isinstance(text, str) or not text.strip():
            _record_skip(summary, rejected, record, REASON_MISSING_TEXT)
            continue

        response = pipeline.validate(text, mode="data_filter")
        meta = response.meta
        annotated = dict(record)
        annotated["_syvern"] = {
            "sample_id": response.sample_id,
            "reward": meta.reward,
            "pass": bool(meta.data_filter_pass),
            "reason": meta.data_filter_reason,
            "validator_fingerprint": meta.validator_fingerprint,
        }

        summary.evaluated += 1
        reason = meta.data_filter_reason or "passed"
        summary.reason_counts[reason] = summary.reason_counts.get(reason, 0) + 1
        if meta.data_filter_pass:
            summary.passed += 1
            kept.append(annotated)
        else:
            summary.dropped += 1
            rejected.append(annotated)

    return SftFilterResult(summary=summary, kept=kept, rejected=rejected)


def _load_record(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _record_skip(
    summary: SftFilterSummary,
    rejected: list[dict[str, Any]],
    record: dict[str, Any],
    reason: str,
) -> None:
    summary.skipped += 1
    summary.reason_counts[reason] = summary.reason_counts.get(reason, 0) + 1
    annotated = dict(record)
    annotated["_syvern"] = {"pass": False, "reason": reason}
    rejected.append(annotated)
