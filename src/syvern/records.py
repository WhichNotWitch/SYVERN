from __future__ import annotations

from dataclasses import dataclass

from syvern.models import Mode, ValidateResponse
from syvern.robustness import semantic_pass


@dataclass(frozen=True)
class ValidationRecord:
    sample_id: str
    text_hash: str
    mode: Mode
    validator_fingerprint: str
    cache_hit: bool
    semantic_pass: bool
    t0_pass: bool
    t1_available: bool
    veto_triggered: bool
    veto_reason: str | None
    requirement_coverage: float
    stable_at_k: float | None
    reward: float
    latency_ms: int
    metadata: dict[str, str]


class InMemoryValidationRecordStore:
    def __init__(self) -> None:
        self._records: list[ValidationRecord] = []

    def add(self, record: ValidationRecord) -> None:
        self._records.append(record)

    def list(self) -> list[ValidationRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()


def make_validation_record(
    response: ValidateResponse,
    *,
    metadata: dict[str, str] | None,
) -> ValidationRecord:
    return ValidationRecord(
        sample_id=response.sample_id,
        text_hash=response.meta.text_hash,
        mode=response.meta.mode,
        validator_fingerprint=response.meta.validator_fingerprint,
        cache_hit=response.meta.cache_hit,
        semantic_pass=semantic_pass(response),
        t0_pass=response.tier_summary.t0_pass,
        t1_available=response.tier_summary.t1_available,
        veto_triggered=response.veto.triggered,
        veto_reason=response.veto.reason,
        requirement_coverage=response.structural.requirement_coverage if response.structural.evaluated else 0.0,
        stable_at_k=response.robustness.stable_at_k,
        reward=response.meta.reward,
        latency_ms=response.meta.latency_ms,
        metadata=dict(metadata or {}),
    )
