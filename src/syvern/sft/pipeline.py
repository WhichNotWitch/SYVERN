from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from syvern.coverage.base import CoverageEvaluator
from syvern.coverage.schema import CoverageReport
from syvern.coverage.simple import SimpleCoverageEvaluator
from syvern.sft.exporter import dataclass_to_dict, write_json, write_jsonl
from syvern.sft.loader import load_sft_samples
from syvern.sft.policy import decide_sft_keep
from syvern.sft.report import increment_count, keep_ratio
from syvern.sft.schema import SftSample


ValidationFn = Callable[[SftSample], object]


@dataclass(frozen=True)
class SftPrepareResult:
    kept: list[dict]
    rejected: list[dict]
    summary: dict


def run_sft_prepare(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    validator: ValidationFn,
    requirement_field: str = "input",
    sysml_field: str = "output",
    coverage_backend: str = "simple",
    min_coverage: float = 0.6,
) -> SftPrepareResult:
    samples = load_sft_samples(
        input_path,
        requirement_field=requirement_field,
        sysml_field=sysml_field,
    )
    evaluator = _coverage_evaluator(coverage_backend, min_coverage)
    require_coverage = evaluator is not None
    kept: list[dict] = []
    rejected: list[dict] = []
    reason_counts: dict[str, int] = {}
    validator_fingerprint: str | None = None

    for sample in samples:
        validation = validator(sample)
        validator_fingerprint = validator_fingerprint or _validation_fingerprint(validation)
        coverage = (
            evaluator.evaluate(
                sample.requirement_text,
                sample.sysml_text,
                sample_id=sample.sample_id,
                metadata=sample.metadata,
            )
            if evaluator is not None
            else None
        )
        keep, reason = decide_sft_keep(
            validation,
            coverage,
            require_coverage=require_coverage,
            min_coverage=min_coverage,
        )
        increment_count(reason_counts, reason)
        annotated = _annotate(sample, validation, coverage, keep=keep, reason=reason)
        if keep:
            kept.append(annotated)
        else:
            rejected.append(annotated)

    summary = {
        "read": len(samples),
        "kept": len(kept),
        "rejected": len(rejected),
        "keep_ratio": keep_ratio(len(kept), len(samples)),
        "coverage_backend": coverage_backend,
        "min_coverage": min_coverage,
        "reason_counts": dict(sorted(reason_counts.items())),
        "validator_fingerprint": validator_fingerprint,
    }
    output = Path(output_dir)
    write_jsonl(output / "kept.jsonl", kept)
    write_jsonl(output / "rejected.jsonl", rejected)
    write_json(output / "report.json", summary)
    return SftPrepareResult(kept=kept, rejected=rejected, summary=summary)


def _coverage_evaluator(coverage_backend: str, min_coverage: float) -> CoverageEvaluator | None:
    if coverage_backend == "none":
        return None
    if coverage_backend == "simple":
        return SimpleCoverageEvaluator(min_coverage=min_coverage)
    raise ValueError(f"unsupported coverage backend {coverage_backend}")


def _annotate(
    sample: SftSample,
    validation: object,
    coverage: CoverageReport | None,
    *,
    keep: bool,
    reason: str,
) -> dict:
    annotated = dict(sample.raw_record)
    if coverage is not None:
        annotated["_syvern_coverage"] = dataclass_to_dict(coverage)
    annotated["_syvern_sft"] = {
        "keep": keep,
        "reason": reason,
        "sample_id": _validation_sample_id(sample, validation),
        "reward": _validation_reward(validation),
        "validator_fingerprint": _validation_fingerprint(validation),
    }
    return annotated


def _validation_fingerprint(validation: object) -> str | None:
    meta = getattr(validation, "meta", None)
    value = getattr(meta, "validator_fingerprint", None)
    return str(value) if value else None


def _validation_reward(validation: object) -> object | None:
    meta = getattr(validation, "meta", None)
    return getattr(meta, "reward", None)


def _validation_sample_id(sample: SftSample, validation: object) -> str:
    value = getattr(validation, "sample_id", None)
    return str(value or sample.sample_id)
