from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


PROMPT_VERSION = "instruction-aug-v1"
EXPECTED_VARIANTS = ("zh_task", "zh_structural", "en_task")
EXPECTED_LANGUAGES = ("zh", "en")
FORBIDDEN_PHRASES = (
    "the code below",
    "same as this output",
    "copy exactly",
    "复制",
    "完全相同",
)
GENERIC_IDENTIFIERS = {
    "SysML",
    "Model",
    "System",
    "Vehicle",
    "Create",
    "Write",
    "Define",
}
MIN_INSTRUCTION_CHARS = 8
MAX_INSTRUCTION_CHARS = 500


@dataclass(frozen=True)
class AugmentationConfig:
    teacher_model: str
    teacher_base_url: str
    prompt_version: str = PROMPT_VERSION


@dataclass(frozen=True)
class TeacherCandidate:
    variant: str
    language: str
    instruction: str


def output_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_teacher_payload(payload: str) -> list[TeacherCandidate]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("teacher payload must be a JSON object")
    raw_candidates = data.get("instructions")
    if not isinstance(raw_candidates, list):
        raise ValueError("teacher payload must contain an instructions list")

    candidates: list[TeacherCandidate] = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            raise ValueError("instruction candidates must be JSON objects")
        variant = raw.get("variant")
        language = raw.get("language")
        instruction = raw.get("instruction")
        if not isinstance(variant, str) or not isinstance(language, str) or not isinstance(
            instruction, str
        ):
            raise ValueError("candidate variant, language, and instruction must be strings")
        candidates.append(
            TeacherCandidate(
                variant=variant.strip(),
                language=language.strip(),
                instruction=instruction.strip(),
            )
        )
    return candidates


def select_sample_records(records: Iterable[Mapping[str, Any]], *, limit: int) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    covered: set[str] = set()
    remaining = list(records)

    while remaining and len(selected) < limit:
        best_index = 0
        best_gain = -1
        for index, record in enumerate(remaining):
            constructs = _construct_set(record)
            gain = len(constructs - covered)
            if gain > best_gain:
                best_index = index
                best_gain = gain
        record = remaining.pop(best_index)
        selected.append(record)
        covered.update(_construct_set(record))

    return selected


def build_augmented_records(
    parent: Mapping[str, Any],
    candidates: Iterable[TeacherCandidate],
    *,
    config: AugmentationConfig,
    batch_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output = str(parent.get("output", ""))
    output_hash = output_sha256(output)
    parent_id = str(parent.get("id", ""))
    augmented: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_instructions: set[str] = set()

    for candidate in candidates:
        failure_reason = _candidate_failure_reason(
            candidate,
            output=output,
            output_hash=output_hash,
            expected_output_hash=output_sha256(output),
            seen_instructions=seen_instructions,
        )
        if failure_reason is not None:
            failures.append(_failure(parent_id, candidate, failure_reason))
            continue

        seen_instructions.add(_normalize_instruction(candidate.instruction))
        record = dict(parent)
        record["id"] = f"{parent_id}__instr_{candidate.variant}"
        record["instruction"] = candidate.instruction
        record["_syvern_instruction_aug"] = {
            "augmented_from": parent_id,
            "parent_output_sha256": output_hash,
            "teacher_model": config.teacher_model,
            "teacher_base_url_host": _url_host(config.teacher_base_url),
            "prompt_version": config.prompt_version,
            "language": candidate.language,
            "variant": candidate.variant,
            "batch_id": batch_id,
            "checks": {
                "passed": True,
                "warnings": _candidate_warnings(candidate, output=output),
            },
        }
        augmented.append(record)

    return augmented, failures


def summarize_augmentation(
    *,
    source_count: int,
    augmented: Iterable[Mapping[str, Any]],
    failures: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    augmented_rows = list(augmented)
    failure_rows = list(failures)
    language_counts: Counter[str] = Counter()
    variant_counts: Counter[str] = Counter()
    failure_reason_counts: Counter[str] = Counter()

    for row in augmented_rows:
        meta = row.get("_syvern_instruction_aug")
        if not isinstance(meta, dict):
            continue
        language = meta.get("language")
        variant = meta.get("variant")
        if isinstance(language, str):
            language_counts[language] += 1
        if isinstance(variant, str):
            variant_counts[variant] += 1
    for failure in failure_rows:
        reason = failure.get("reason")
        if isinstance(reason, str):
            failure_reason_counts[reason] += 1

    return {
        "source_count": source_count,
        "accepted_count": len(augmented_rows),
        "rejected_count": len(failure_rows),
        "language_counts": dict(sorted(language_counts.items())),
        "variant_counts": dict(sorted(variant_counts.items())),
        "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "failures": failure_rows,
    }


def _construct_set(record: Mapping[str, Any]) -> set[str]:
    constructs = record.get("constructs", [])
    if not isinstance(constructs, list):
        return set()
    return {item for item in constructs if isinstance(item, str)}


def _url_host(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or parsed.path


def _candidate_failure_reason(
    candidate: TeacherCandidate,
    *,
    output: str,
    output_hash: str,
    expected_output_hash: str,
    seen_instructions: set[str],
) -> str | None:
    instruction = candidate.instruction.strip()
    if not instruction:
        return "empty_instruction"
    if len(instruction) < MIN_INSTRUCTION_CHARS or len(instruction) > MAX_INSTRUCTION_CHARS:
        return "invalid_length"
    if candidate.variant not in EXPECTED_VARIANTS:
        return "invalid_variant"
    if candidate.language not in EXPECTED_LANGUAGES:
        return "invalid_language"
    if any(phrase.lower() in instruction.lower() for phrase in FORBIDDEN_PHRASES):
        return "forbidden_phrase"
    if _normalize_instruction(instruction) in seen_instructions:
        return "duplicate_instruction"
    if output_hash != expected_output_hash:
        return "output_hash_mismatch"
    unsupported = _unsupported_identifiers(instruction, output)
    if unsupported:
        return "unsupported_identifier"
    return None


def _candidate_warnings(candidate: TeacherCandidate, *, output: str) -> list[str]:
    identifiers = _instruction_identifiers(candidate.instruction)
    output_identifiers = set(_instruction_identifiers(output))
    meaningful = [identifier for identifier in identifiers if identifier not in GENERIC_IDENTIFIERS]
    if not meaningful:
        return ["low_identifier_overlap"]
    if meaningful and not any(identifier in output_identifiers for identifier in meaningful):
        return ["low_identifier_overlap"]
    return []


def _failure(parent_id: str, candidate: TeacherCandidate, reason: str) -> dict[str, str]:
    return {
        "augmented_from": parent_id,
        "variant": candidate.variant,
        "language": candidate.language,
        "instruction": candidate.instruction,
        "reason": reason,
    }


def _normalize_instruction(text: str) -> str:
    return " ".join(text.split()).casefold()


def _unsupported_identifiers(instruction: str, output: str) -> list[str]:
    output_identifiers = set(_instruction_identifiers(output))
    unsupported: list[str] = []
    for identifier in _instruction_identifiers(instruction):
        if identifier in GENERIC_IDENTIFIERS:
            continue
        if identifier not in output_identifiers:
            unsupported.append(identifier)
    return unsupported


def _instruction_identifiers(text: str) -> list[str]:
    return re.findall(r"\b[A-Z][A-Za-z0-9_]*[a-z0-9][A-Za-z0-9_]*\b", text)
