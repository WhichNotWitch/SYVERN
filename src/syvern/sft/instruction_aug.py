from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


PROMPT_VERSION = "instruction-aug-v1"
EXPECTED_VARIANTS = ("zh_task", "zh_structural", "en_task")


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

    for candidate in candidates:
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
            "checks": {"passed": True, "warnings": []},
        }
        augmented.append(record)

    return augmented, []


def _construct_set(record: Mapping[str, Any]) -> set[str]:
    constructs = record.get("constructs", [])
    if not isinstance(constructs, list):
        return set()
    return {item for item in constructs if isinstance(item, str)}


def _url_host(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or parsed.path
