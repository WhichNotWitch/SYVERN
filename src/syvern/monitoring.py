from __future__ import annotations

from collections import defaultdict

from syvern.models import (
    DashboardRecentRecord,
    DashboardSnapshot,
    DashboardTenantSummary,
    DivergenceAlert,
    MonitorAggregateSummary,
)
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


def _stable_at_k_by_prompt(records: list[ValidationRecord]) -> float:
    groups: dict[str, list[ValidationRecord]] = defaultdict(list)
    for index, record in enumerate(records):
        prompt_key = record.prompt_id or f"record:{index}:{record.text_hash}"
        groups[prompt_key].append(record)
    return _average(
        [
            _rate(sum(1 for record in group if record.semantic_pass), len(group))
            for group in groups.values()
        ]
    )


def aggregate_monitor_summary(records: list[ValidationRecord]) -> MonitorAggregateSummary:
    total = len(records)
    formal_records = [record for record in records if record.formal_evaluated]
    formal_total = len(formal_records)
    return MonitorAggregateSummary(
        record_count=total,
        semantic_pass_rate=_rate(sum(1 for record in records if record.semantic_pass), total),
        t0_pass_rate=_rate(sum(1 for record in records if record.t0_pass), total),
        t1_available_rate=_rate(sum(1 for record in records if record.t1_available), total),
        veto_rate=_rate(sum(1 for record in records if record.veto_triggered), total),
        average_requirement_coverage=_average([record.requirement_coverage for record in records]),
        average_reward=_average([record.reward for record in records]),
        average_latency_ms=_average([float(record.latency_ms) for record in records]),
        stable_at_k=_stable_at_k_by_prompt(records),
        formal_evaluated_count=formal_total,
        formal_proved_rate=_rate(sum(1 for record in formal_records if record.formal_status == "proved"), formal_total),
        formal_failed_rate=_rate(sum(1 for record in formal_records if record.formal_status == "failed"), formal_total),
        formal_timeout_rate=_rate(sum(1 for record in formal_records if record.formal_status == "timeout"), formal_total),
        formal_error_rate=_rate(sum(1 for record in formal_records if record.formal_status == "error"), formal_total),
        divergence_alerts=[],
    )


def aggregate_dashboard_snapshot(
    records: list[ValidationRecord],
    *,
    summary: MonitorAggregateSummary,
    validator_fingerprint: str,
    recent_limit: int,
) -> DashboardSnapshot:
    tenant_groups: dict[str, list[ValidationRecord]] = defaultdict(list)
    for record in records:
        tenant_id = record.metadata.get("tenant_id") or "unassigned"
        tenant_groups[tenant_id].append(record)

    tenant_summaries = [
        DashboardTenantSummary(
            tenant_id=tenant_id,
            record_count=len(group),
            semantic_pass_rate=_rate(sum(1 for record in group if record.semantic_pass), len(group)),
            average_reward=_average([record.reward for record in group]),
        )
        for tenant_id, group in sorted(tenant_groups.items())
    ]
    recent_records = [
        DashboardRecentRecord(
            sample_id=record.sample_id,
            text_hash=record.text_hash,
            mode=record.mode,
            cache_hit=record.cache_hit,
            semantic_pass=record.semantic_pass,
            t0_pass=record.t0_pass,
            veto_triggered=record.veto_triggered,
            veto_reason=record.veto_reason,
            reward=record.reward,
            latency_ms=record.latency_ms,
            tenant_id=record.metadata.get("tenant_id"),
            prompt_id=record.prompt_id,
            formal_status=record.formal_status,
        )
        for record in reversed(records[-recent_limit:] if recent_limit > 0 else [])
    ]
    return DashboardSnapshot(
        validator_fingerprint=validator_fingerprint,
        summary=summary,
        tenant_summaries=tenant_summaries,
        recent_records=recent_records,
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
