from __future__ import annotations

from syvern.models import DivergenceAlert, MonitorAggregateSummary
from syvern.records import ValidationRecord
from syvern.settings import SyvernSettings


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return count / total


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def aggregate_monitor_summary(records: list[ValidationRecord]) -> MonitorAggregateSummary:
    total = len(records)
    return MonitorAggregateSummary(
        record_count=total,
        semantic_pass_rate=_rate(sum(1 for record in records if record.semantic_pass), total),
        t0_pass_rate=_rate(sum(1 for record in records if record.t0_pass), total),
        t1_available_rate=_rate(sum(1 for record in records if record.t1_available), total),
        veto_rate=_rate(sum(1 for record in records if record.veto_triggered), total),
        average_requirement_coverage=_average([record.requirement_coverage for record in records]),
        average_reward=_average([record.reward for record in records]),
        average_latency_ms=_average([float(record.latency_ms) for record in records]),
        stable_at_k=_rate(sum(1 for record in records if record.semantic_pass), total),
        divergence_alerts=[],
    )


def detect_divergence(
    previous: MonitorAggregateSummary,
    current: MonitorAggregateSummary,
    settings: SyvernSettings,
) -> list[DivergenceAlert]:
    if previous.record_count == 0 or current.record_count == 0:
        return []

    alerts: list[DivergenceAlert] = []
    semantic_gain = current.semantic_pass_rate - previous.semantic_pass_rate
    coverage_gain = current.average_requirement_coverage - previous.average_requirement_coverage
    veto_gain = current.veto_rate - previous.veto_rate
    stable_drop = previous.stable_at_k - current.stable_at_k

    if (
        semantic_gain >= settings.monitor_semantic_gain_threshold
        and coverage_gain <= settings.monitor_coverage_stall_threshold
    ):
        alerts.append(
            DivergenceAlert(
                code="semantic_without_coverage",
                message="semantic pass rate increased while requirement coverage stalled",
                severity="warn",
            )
        )
    if veto_gain >= settings.monitor_veto_rate_increase_threshold:
        alerts.append(
            DivergenceAlert(
                code="veto_rate_increase",
                message="veto rate increased beyond the H6 monitoring threshold",
                severity="warn",
            )
        )
    if stable_drop >= settings.monitor_stable_drop_threshold:
        alerts.append(
            DivergenceAlert(
                code="stable_at_k_drop",
                message="stable_at_k dropped beyond the H6 monitoring threshold",
                severity="warn",
            )
        )
    return alerts
