from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Sequence

from syvern.coverage.simple import SimpleCoverageEvaluator
from syvern.adapters.base import ValidatorAdapter
from syvern.adapters.pilot import PilotAdapter
from syvern.alignment import (
    AlignmentSummary,
    calibrated_case_payloads,
    load_alignment_cases,
    run_adapter_alignment,
)
from syvern.benchmark import OnlineRewardBenchmarkSummary, benchmark_online_reward
from syvern.pipeline_factory import build_validation_pipeline
from syvern.settings import load_settings_from_env
from syvern.sft import SftFilterResult, run_sft_filter
from syvern.sft.exporter import dataclass_to_dict
from syvern.sft.loader import load_sft_samples
from syvern.sft.pipeline import run_sft_prepare


def _adapter(name: str) -> ValidatorAdapter:
    if name == "pilot":
        settings = load_settings_from_env()
        return PilotAdapter(settings.pilot_endpoint, settings.pilot_version, settings.pilot_timeout_s)
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
    min_element: float,
    min_cases: int,
    required_categories: Sequence[str],
) -> bool:
    return (
        summary.total >= min_cases
        and summary.overall_accuracy >= min_overall
        and summary.parse_accuracy >= min_parse
        and summary.resolve_accuracy >= min_resolve
        and summary.typecheck_accuracy >= min_typecheck
        and summary.element_accuracy >= min_element
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


def _write_calibrated(path: str, payloads: list[dict[str, object]]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        handle.write(
            "# Calibrated alignment corpus emitted from adapter actual output. Review before adopting.\n"
        )
        for payload in payloads:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _load_benchmark_samples(path: str) -> list[str]:
    samples = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return [sample for sample in samples if sample]


def _filter_payload(result: SftFilterResult) -> dict:
    s = result.summary
    return {
        "read": s.read,
        "evaluated": s.evaluated,
        "passed": s.passed,
        "dropped": s.dropped,
        "skipped": s.skipped,
        "keep_ratio": s.keep_ratio,
        "reason_counts": s.reason_counts,
    }


def _write_jsonl(path: str, records: list[dict]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _write_coverage_jsonl(
    *,
    input_path: str,
    output_path: str,
    requirement_field: str,
    sysml_field: str,
    min_coverage: float,
) -> None:
    evaluator = SimpleCoverageEvaluator(min_coverage=min_coverage)
    samples = load_sft_samples(
        input_path,
        requirement_field=requirement_field,
        sysml_field=sysml_field,
    )
    rows = [
        dataclass_to_dict(
            evaluator.evaluate(
                sample.requirement_text,
                sample.sysml_text,
                sample_id=sample.sample_id,
                metadata=sample.metadata,
            )
        )
        for sample in samples
    ]
    _write_jsonl(output_path, rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syvern")
    subparsers = parser.add_subparsers(dest="command", required=True)

    align = subparsers.add_parser("align", help="run an adapter alignment dataset")
    align.add_argument("--adapter", choices=["pilot"], required=True)
    align.add_argument("--dataset", required=True)
    align.add_argument("--min-overall", type=float, default=1.0)
    align.add_argument("--min-parse", type=float, default=0.0)
    align.add_argument("--min-resolve", type=float, default=0.0)
    align.add_argument("--min-typecheck", type=float, default=0.0)
    align.add_argument("--min-element-accuracy", type=float, default=0.0)
    align.add_argument("--min-cases", type=int, default=1)
    align.add_argument("--require-category", action="append", default=[])
    align.add_argument(
        "--emit-calibrated",
        default=None,
        help="write a candidate corpus from the adapter's actual output (calibration), then exit 0",
    )

    benchmark = subparsers.add_parser("benchmark", help="run an online_reward latency benchmark")
    benchmark.add_argument("--samples", required=True)
    benchmark.add_argument("--max-average-latency-ms", type=float, default=None)
    benchmark.add_argument("--min-throughput-per-s", type=float, default=None)

    sft = subparsers.add_parser("filter", help="filter an SFT JSONL corpus via the data_filter path")
    sft.add_argument("--dataset", required=True, help="input JSONL; one record per line")
    sft.add_argument("--text-field", default="text", help="record key holding the SysML v2 text")
    sft.add_argument("--output", default=None, help="write kept (passing) records to this JSONL")
    sft.add_argument("--rejected", default=None, help="write dropped/skipped records to this JSONL")
    sft.add_argument(
        "--min-reward",
        type=float,
        default=None,
        help="override SYVERN_DATA_FILTER_MIN_REWARD for this run",
    )
    sft.add_argument(
        "--min-keep-ratio",
        type=float,
        default=None,
        help="exit non-zero if the kept fraction falls below this threshold",
    )

    coverage = subparsers.add_parser("coverage", help="coverage utilities")
    coverage_subparsers = coverage.add_subparsers(dest="coverage_command", required=True)
    coverage_simple = coverage_subparsers.add_parser("simple", help="run simple requirement coverage")
    coverage_simple.add_argument("--input", required=True)
    coverage_simple.add_argument("--output", required=True)
    coverage_simple.add_argument("--requirement-field", default="input")
    coverage_simple.add_argument("--sysml-field", default="output")
    coverage_simple.add_argument("--min-coverage", type=float, default=0.6)

    sft_group = subparsers.add_parser("sft", help="SFT data preparation")
    sft_subparsers = sft_group.add_subparsers(dest="sft_command", required=True)
    sft_prepare = sft_subparsers.add_parser("prepare", help="validate, cover, and split SFT candidates")
    sft_prepare.add_argument("--input", required=True)
    sft_prepare.add_argument("--output-dir", required=True)
    sft_prepare.add_argument("--requirement-field", default="input")
    sft_prepare.add_argument("--sysml-field", default="output")
    sft_prepare.add_argument("--coverage-backend", choices=["simple", "none"], default="simple")
    sft_prepare.add_argument("--min-coverage", type=float, default=0.6)

    args = parser.parse_args(argv)
    if args.command == "align":
        cases = load_alignment_cases(args.dataset)
        adapter = _adapter(args.adapter)
        alignment_summary = run_adapter_alignment(adapter, cases)
        print(json.dumps(_alignment_payload(alignment_summary), sort_keys=True))
        if args.emit_calibrated:
            _write_calibrated(args.emit_calibrated, calibrated_case_payloads(adapter, cases))
            return 0
        return (
            0
            if _alignment_passes(
                alignment_summary,
                min_overall=args.min_overall,
                min_parse=args.min_parse,
                min_resolve=args.min_resolve,
                min_typecheck=args.min_typecheck,
                min_element=args.min_element_accuracy,
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
    if args.command == "filter":
        settings = load_settings_from_env()
        if args.min_reward is not None:
            settings = replace(settings, data_filter_min_reward=args.min_reward)
        pipeline = build_validation_pipeline(settings)
        lines = Path(args.dataset).read_text(encoding="utf-8").splitlines()
        result = run_sft_filter(pipeline, lines, text_field=args.text_field)
        if args.output is not None:
            _write_jsonl(args.output, result.kept)
        if args.rejected is not None:
            _write_jsonl(args.rejected, result.rejected)
        print(json.dumps(_filter_payload(result), sort_keys=True))
        if args.min_keep_ratio is not None and result.summary.keep_ratio < args.min_keep_ratio:
            return 1
        return 0
    if args.command == "coverage":
        if args.coverage_command == "simple":
            _write_coverage_jsonl(
                input_path=args.input,
                output_path=args.output,
                requirement_field=args.requirement_field,
                sysml_field=args.sysml_field,
                min_coverage=args.min_coverage,
            )
            return 0
    if args.command == "sft":
        if args.sft_command == "prepare":
            settings = load_settings_from_env()
            pipeline = build_validation_pipeline(settings)

            def validate_sample(sample):
                return pipeline.validate(sample.sysml_text, mode="data_filter")

            result = run_sft_prepare(
                args.input,
                args.output_dir,
                validator=validate_sample,
                requirement_field=args.requirement_field,
                sysml_field=args.sysml_field,
                coverage_backend=args.coverage_backend,
                min_coverage=args.min_coverage,
            )
            print(json.dumps(result.summary, sort_keys=True))
            return 0
    raise AssertionError(f"unhandled command {args.command}")


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
