#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from syvern.sft.dataset import write_jsonl
from syvern.sft.filter_api import filter_records_with_validate_batch, make_http_validate_batch


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
    parser = argparse.ArgumentParser(description="Filter SFT candidates with SYVERN /validate_batch.")
    parser.add_argument("--in", dest="input_path", required=True)
    parser.add_argument("--kept", required=True)
    parser.add_argument("--rejected", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--expect-fingerprint", default=None)
    args = parser.parse_args(argv)

    result = filter_records_with_validate_batch(
        _load_jsonl(Path(args.input_path)),
        make_http_validate_batch(args.endpoint, timeout_s=args.timeout_s),
        batch_size=args.batch_size,
        expected_fingerprint=args.expect_fingerprint,
    )
    write_jsonl(Path(args.kept), result.kept)
    write_jsonl(Path(args.rejected), result.rejected)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
