from syvern.monitoring import aggregate_monitor_summary, detect_divergence
from syvern.records import ValidationRecord
from syvern.settings import SyvernSettings


def _record(
    *,
    semantic_pass: bool = True,
    t0_pass: bool = True,
    t1_available: bool = False,
    veto_triggered: bool = False,
    requirement_coverage: float = 0.0,
    reward: float = 0.5,
    latency_ms: int = 4,
    prompt_id: str | None = None,
    formal_evaluated: bool = False,
    formal_status: str | None = None,
) -> ValidationRecord:
    return ValidationRecord(
        sample_id="sample",
        text_hash="hash",
        mode="online_reward",
        validator_fingerprint="fingerprint",
        cache_hit=False,
        semantic_pass=semantic_pass,
        t0_pass=t0_pass,
        t1_available=t1_available,
        veto_triggered=veto_triggered,
        veto_reason="forced" if veto_triggered else None,
        requirement_coverage=requirement_coverage,
        stable_at_k=None,
        reward=reward,
        latency_ms=latency_ms,
        prompt_id=prompt_id,
        formal_evaluated=formal_evaluated,
        formal_status=formal_status,
        metadata={},
    )


def test_empty_monitor_summary_returns_zero_rates_and_no_alerts():
    summary = aggregate_monitor_summary([])

    assert summary.record_count == 0
    assert summary.semantic_pass_rate == 0.0
    assert summary.t0_pass_rate == 0.0
    assert summary.t1_available_rate == 0.0
    assert summary.veto_rate == 0.0
    assert summary.average_requirement_coverage == 0.0
    assert summary.average_reward == 0.0
    assert summary.average_latency_ms == 0.0
    assert summary.stable_at_k == 0.0
    assert summary.formal_evaluated_count == 0
    assert summary.formal_proved_rate == 0.0
    assert summary.formal_failed_rate == 0.0
    assert summary.formal_timeout_rate == 0.0
    assert summary.formal_error_rate == 0.0
    assert summary.divergence_alerts == []


def test_monitor_summary_computes_rates_and_averages():
    summary = aggregate_monitor_summary(
        [
            _record(requirement_coverage=1.0, reward=1.0, latency_ms=10, t1_available=True),
            _record(semantic_pass=False, t0_pass=False, veto_triggered=True, reward=0.0, latency_ms=20),
        ]
    )

    assert summary.record_count == 2
    assert summary.semantic_pass_rate == 0.5
    assert summary.t0_pass_rate == 0.5
    assert summary.t1_available_rate == 0.5
    assert summary.veto_rate == 0.5
    assert summary.average_requirement_coverage == 0.5
    assert summary.average_reward == 0.5
    assert summary.average_latency_ms == 15.0
    assert summary.stable_at_k == 0.5
    assert summary.formal_evaluated_count == 0
    assert summary.divergence_alerts == []


def test_monitor_summary_aggregates_formal_status_rates_over_evaluated_runs():
    summary = aggregate_monitor_summary(
        [
            _record(formal_evaluated=True, formal_status="proved"),
            _record(formal_evaluated=True, formal_status="failed"),
            _record(formal_evaluated=True, formal_status="timeout"),
            _record(formal_evaluated=True, formal_status="error"),
            _record(formal_evaluated=False, formal_status=None),
        ]
    )

    assert summary.record_count == 5
    assert summary.formal_evaluated_count == 4
    assert summary.formal_proved_rate == 0.25
    assert summary.formal_failed_rate == 0.25
    assert summary.formal_timeout_rate == 0.25
    assert summary.formal_error_rate == 0.25


def test_monitor_summary_computes_stable_at_k_by_prompt_group():
    summary = aggregate_monitor_summary(
        [
            _record(prompt_id="prompt-a", semantic_pass=True),
            _record(prompt_id="prompt-a", semantic_pass=False, t0_pass=False),
            _record(prompt_id="prompt-b", semantic_pass=True),
        ]
    )

    assert summary.semantic_pass_rate == 2 / 3
    assert summary.stable_at_k == 0.75


def test_divergence_flags_semantic_gain_without_coverage_gain():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary(
        [_record(semantic_pass=False, t0_pass=False, requirement_coverage=0.2) for _ in range(5)]
    )
    current = aggregate_monitor_summary(
        [_record(semantic_pass=True, t0_pass=True, requirement_coverage=0.22) for _ in range(5)]
    )

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["semantic_without_coverage"]
    assert alerts[0].severity == "warn"


def test_divergence_ignores_empty_windows():
    settings = SyvernSettings()
    empty = aggregate_monitor_summary([])
    populated = aggregate_monitor_summary([_record(semantic_pass=True) for _ in range(5)])

    assert detect_divergence(empty, populated, settings) == []
    assert detect_divergence(populated, empty, settings) == []


def test_divergence_flags_veto_rate_increase():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary([_record(veto_triggered=False) for _ in range(5)])
    current = aggregate_monitor_summary([_record(veto_triggered=True) for _ in range(5)])

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["veto_rate_increase"]


def test_divergence_flags_stable_at_k_drop():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary([_record(semantic_pass=True) for _ in range(5)])
    current = aggregate_monitor_summary([_record(semantic_pass=False, t0_pass=False) for _ in range(5)])

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["stable_at_k_drop"]
