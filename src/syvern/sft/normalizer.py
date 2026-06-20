from __future__ import annotations

from typing import Any, Mapping

from syvern.sft.schema import SftSample


def normalize_sft_record(
    record: Mapping[str, Any],
    *,
    requirement_field: str = "input",
    sysml_field: str = "output",
) -> SftSample:
    sample_id = str(record.get("id") or record.get("sample_id") or "")
    if not sample_id.strip():
        raise ValueError("SFT record needs id or sample_id")
    requirement = record.get(requirement_field, record.get("requirement_text", ""))
    sysml = record.get(sysml_field, record.get("sysml_text"))
    if not isinstance(requirement, str):
        raise ValueError(f"{sample_id}: requirement field must be a string")
    if not isinstance(sysml, str) or not sysml.strip():
        raise ValueError(f"{sample_id}: SysML field must be a non-empty string")
    metadata = dict(record.get("metadata") or {})
    if "coverage_spec" in record:
        metadata["coverage_spec"] = record["coverage_spec"]
    return SftSample(
        sample_id=sample_id,
        requirement_text=requirement,
        sysml_text=sysml,
        source=record.get("source", "unknown"),
        task_type=str(record.get("task_type") or "nl_to_sysml"),
        metadata=metadata,
        raw_record=dict(record),
    )
