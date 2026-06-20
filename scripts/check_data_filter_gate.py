#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from syvern.data_filter_gate import run_data_filter_gate_check
from syvern.pipeline_factory import build_validation_pipeline
from syvern.settings import load_settings_from_env


def _load_records(path: str) -> list[dict]:
    records: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("each JSONL line must be an object")
        records.append(payload)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare data_filter decisions with keep_expected.")
    parser.add_argument("--in", dest="path", required=True, help="manual alignment JSONL")
    parser.add_argument("--min-accuracy", type=float, default=1.0)
    args = parser.parse_args(argv)

    pipeline = build_validation_pipeline(load_settings_from_env())
    summary = run_data_filter_gate_check(pipeline, _load_records(args.path))
    print(json.dumps(asdict(summary), sort_keys=True))
    return 0 if summary.accuracy >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
