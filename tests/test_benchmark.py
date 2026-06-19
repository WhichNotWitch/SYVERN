from syvern.benchmark import benchmark_online_reward
from syvern.pipeline import ValidationPipeline


def test_benchmark_online_reward_reports_latency_and_throughput():
    ticks = iter([10.0, 10.5])

    summary = benchmark_online_reward(
        ValidationPipeline(),
        [
            "part vehicle.engine attribute vehicle.mass",
            "part vehicle.body connection vehicle.body_to_engine",
        ],
        now=lambda: next(ticks),
    )

    assert summary.sample_count == 2
    assert summary.elapsed_s == 0.5
    assert summary.average_latency_ms == 250.0
    assert summary.throughput_per_s == 4.0
    assert summary.semantic_pass_count == 2


def test_benchmark_online_reward_rejects_empty_sample_set():
    try:
        benchmark_online_reward(ValidationPipeline(), [])
    except ValueError as exc:
        assert str(exc) == "benchmark samples must not be empty"
    else:
        raise AssertionError("expected empty benchmark samples to be rejected")
