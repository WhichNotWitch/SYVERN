from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from syvern.pipeline import ValidationPipeline


@dataclass(frozen=True)
class OnlineRewardBenchmarkSummary:
    sample_count: int
    elapsed_s: float
    average_latency_ms: float
    throughput_per_s: float
    semantic_pass_count: int


def benchmark_online_reward(
    pipeline: ValidationPipeline,
    samples: Sequence[str],
    *,
    now: Callable[[], float] = perf_counter,
) -> OnlineRewardBenchmarkSummary:
    if not samples:
        raise ValueError("benchmark samples must not be empty")

    started = now()
    responses = [pipeline.validate(sample, mode="online_reward") for sample in samples]
    elapsed_s = now() - started
    sample_count = len(samples)
    return OnlineRewardBenchmarkSummary(
        sample_count=sample_count,
        elapsed_s=elapsed_s,
        average_latency_ms=(elapsed_s / sample_count) * 1000,
        throughput_per_s=sample_count / elapsed_s if elapsed_s > 0 else float("inf"),
        semantic_pass_count=sum(response.tier_summary.t0_pass for response in responses),
    )
