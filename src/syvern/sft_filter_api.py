from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen


ValidateBatchFn = Callable[[list[str]], Mapping[str, Any]]


@dataclass(frozen=True)
class SftFilterApiResult:
    kept: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    summary: dict[str, Any]


def filter_records_with_validate_batch(
    records: Iterable[dict[str, Any]],
    validate_batch: ValidateBatchFn,
    *,
    batch_size: int = 32,
    expected_fingerprint: str | None = None,
) -> SftFilterApiResult:
    record_list = list(records)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    validator_fingerprint: str | None = None

    for start in range(0, len(record_list), batch_size):
        batch = record_list[start : start + batch_size]
        texts = [str(record.get("output", "")) for record in batch]
        payload = validate_batch(texts)
        responses = payload.get("responses")
        if not isinstance(responses, list) or len(responses) != len(batch):
            raise ValueError("validate_batch response count did not match request count")
        for record, response in zip(batch, responses):
            if not isinstance(response, dict):
                raise ValueError("validate_batch responses must be objects")
            meta = response.get("meta")
            if not isinstance(meta, dict):
                raise ValueError("validate_batch response missing meta")
            fingerprint = str(meta.get("validator_fingerprint", ""))
            if expected_fingerprint is not None and fingerprint != expected_fingerprint:
                raise ValueError(f"unexpected validator fingerprint {fingerprint}")
            validator_fingerprint = validator_fingerprint or fingerprint
            passed = bool(meta.get("data_filter_pass"))
            reason = str(meta.get("data_filter_reason") or ("passed" if passed else "unknown"))
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            annotated = dict(record)
            annotated["_syvern"] = {
                "sample_id": response.get("sample_id"),
                "reward": meta.get("reward"),
                "pass": passed,
                "reason": reason,
                "validator_fingerprint": fingerprint,
            }
            if passed:
                kept.append(annotated)
            else:
                rejected.append(annotated)

    read = len(record_list)
    passed_count = len(kept)
    return SftFilterApiResult(
        kept=kept,
        rejected=rejected,
        summary={
            "read": read,
            "passed": passed_count,
            "rejected": len(rejected),
            "pass_rate": passed_count / read if read else 0.0,
            "reason_counts": dict(sorted(reason_counts.items())),
            "validator_fingerprint": validator_fingerprint,
        },
    )


def make_http_validate_batch(
    endpoint: str,
    *,
    timeout_s: float = 30.0,
    mode: str = "data_filter",
) -> ValidateBatchFn:
    url = f"{endpoint.rstrip('/')}/validate_batch"

    def validate_batch(texts: list[str]) -> Mapping[str, Any]:
        request = Request(
            url,
            data=json.dumps({"texts": texts, "mode": mode}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("validate_batch returned a non-object payload")
        return payload

    return validate_batch
