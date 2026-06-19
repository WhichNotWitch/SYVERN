from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter
from syvern.alignment import AlignmentSummary, load_alignment_cases, run_adapter_alignment
from syvern.benchmark import OnlineRewardBenchmarkSummary, benchmark_online_reward
from syvern.pipeline_factory import build_validation_pipeline
from syvern.settings import load_settings_from_env


def _adapter(name: str) -> PilotStubAdapter | MontiCoreStubAdapter:
    if name == "pilot-stub":
        return PilotStubAdapter()
    if name == "monticore-stub":
        return MontiCoreStubAdapter()
    raise ValueError(f"unsupported adapter {name}")


def _alignment_payload(summary: AlignmentSummary) -> dict:
    return asdict(summary)


def _alignment_passes(
    summary: AlignmentSummary,
    *,
    min_overall: float,
    min_parse: float,
    min_resolve: float,
    min_typecheck: float,
    min_cases: int,
    required_categories: Sequence[str],
) -> bool:
    return (
        summary.total >= min_cases
        and summary.overall_accuracy >= min_overall
        and summary.parse_accuracy >= min_parse
        and summary.resolve_accuracy >= min_resolve
        and summary.typecheck_accuracy >= min_typecheck
        and all(summary.category_counts.get(category, 0) > 0 for category in required_categories)
    )


def _benchmark_payload(summary: OnlineRewardBenchmarkSummary) -> dict:
    return asdict(summary)


def _benchmark_passes(
    summary: OnlineRewardBenchmarkSummary,
    *,
    max_average_latency_ms: float | None,
    min_throughput_per_s: float | None,
) -> bool:
    if max_average_latency_ms is not None and summary.average_latency_ms > max_average_latency_ms:
        return False
    if min_throughput_per_s is not None and summary.throughput_per_s < min_throughput_per_s:
        return False
    return True


def _load_benchmark_samples(path: str) -> list[str]:
    samples = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return [sample for sample in samples if sample]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syvern")
    subparsers = parser.add_subparsers(dest="command", required=True)

    align = subparsers.add_parser("align", help="run an adapter alignment dataset")
    align.add_argument("--adapter", choices=["pilot-stub", "monticore-stub"], required=True)
    align.add_argument("--dataset", required=True)
    align.add_argument("--min-overall", type=float, default=1.0)
    align.add_argument("--min-parse", type=float, default=0.0)
    align.add_argument("--min-resolve", type=float, default=0.0)
    align.add_argument("--min-typecheck", type=float, default=0.0)
    align.add_argument("--min-cases", type=int, default=1)
    align.add_argument("--require-category", action="append", default=[])

    benchmark = subparsers.add_parser("benchmark", help="run an online_reward latency benchmark")
    benchmark.add_argument("--samples", required=True)
    benchmark.add_argument("--max-average-latency-ms", type=float, default=None)
    benchmark.add_argument("--min-throughput-per-s", type=float, default=None)

    args = parser.parse_args(argv)
    if args.command == "align":
        cases = load_alignment_cases(args.dataset)
        alignment_summary = run_adapter_alignment(_adapter(args.adapter), cases)
        print(json.dumps(_alignment_payload(alignment_summary), sort_keys=True))
        return (
            0
            if _alignment_passes(
                alignment_summary,
                min_overall=args.min_overall,
                min_parse=args.min_parse,
                min_resolve=args.min_resolve,
                min_typecheck=args.min_typecheck,
                min_cases=args.min_cases,
                required_categories=args.require_category,
            )
            else 1
        )
    if args.command == "benchmark":
        pipeline = build_validation_pipeline(load_settings_from_env())
        benchmark_summary = benchmark_online_reward(pipeline, _load_benchmark_samples(args.samples))
        print(json.dumps(_benchmark_payload(benchmark_summary), sort_keys=True))
        return (
            0
            if _benchmark_passes(
                benchmark_summary,
                max_average_latency_ms=args.max_average_latency_ms,
                min_throughput_per_s=args.min_throughput_per_s,
            )
            else 1
        )
    raise AssertionError(f"unhandled command {args.command}")


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
