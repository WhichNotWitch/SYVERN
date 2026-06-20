from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from syvern.sft.normalizer import normalize_sft_record
from syvern.sft.schema import SftSample


def load_sft_samples(
    path: str | Path,
    *,
    requirement_field: str = "input",
    sysml_field: str = "output",
) -> list[SftSample]:
    samples: list[SftSample] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: JSONL record must be an object")
        samples.append(
            normalize_sft_record(
                payload,
                requirement_field=requirement_field,
                sysml_field=sysml_field,
            )
        )
    return samples


def load_raw_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: JSONL record must be an object")
        records.append(payload)
    return records
