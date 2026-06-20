#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from syvern.sft_dataset import coverage_counts, dedupe_by_output, split_by_source_file, write_jsonl


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: JSONL records must be objects")
        records.append(payload)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deduplicate and split filtered SFT records by source file.")
    parser.add_argument("--in", dest="input_path", required=True)
    parser.add_argument("--train", required=True)
    parser.add_argument("--val", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    args = parser.parse_args(argv)

    records = _load_jsonl(Path(args.input_path))
    deduped, duplicate_ids = dedupe_by_output(records)
    train, val = split_by_source_file(deduped, val_ratio=args.val_ratio)
    write_jsonl(Path(args.train), train)
    write_jsonl(Path(args.val), val)
    report = {
        "input_records": len(records),
        "deduped_records": len(deduped),
        "duplicate_ids": duplicate_ids,
        "train_records": len(train),
        "val_records": len(val),
        "train_coverage": coverage_counts(train),
        "val_coverage": coverage_counts(val),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
