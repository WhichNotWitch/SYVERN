#!/usr/bin/env python3
"""Augment an SFT split by decomposing multi-package models into self-contained
single-package sub-models, validated standalone through the data_filter gate.

Originals are kept; passing, non-duplicate sub-packages are appended. Use
``--exclude`` to dedup against another split's outputs (leakage prevention):
decompose train first, then decompose val with ``--exclude train.jsonl``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from syvern.pipeline_factory import build_validation_pipeline
from syvern.settings import load_settings_from_env
from syvern.sft.dataset import decompose_records, write_jsonl, _normalize_output


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        records.append(json.loads(stripped))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decompose multi-package SFT models into sub-models.")
    parser.add_argument("--in", dest="input_path", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--exclude", action="append", default=[], help="JSONL whose outputs to also dedup against")
    parser.add_argument("--min-chars", type=int, default=80)
    args = parser.parse_args(argv)

    records = _load_jsonl(Path(args.input_path))
    seen = {_normalize_output(str(r.get("output", ""))) for r in records}
    for extra in args.exclude:
        for r in _load_jsonl(Path(extra)):
            seen.add(_normalize_output(str(r.get("output", ""))))

    pipeline = build_validation_pipeline(load_settings_from_env())

    def validator(text: str) -> bool:
        return bool(pipeline.validate(text, mode="data_filter").meta.data_filter_pass)

    new, report = decompose_records(records, validator, seen_outputs=seen, min_chars=args.min_chars)
    combined = records + new
    write_jsonl(Path(args.out), combined)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {"input_records": len(records), "combined_records": len(combined), **report},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"input": len(records), "added": report["added"], "combined": len(combined)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
