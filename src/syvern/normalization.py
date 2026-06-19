from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


def token_count(text: str) -> int:
    normalized = normalize_ws(text)
    if not normalized:
        return 0
    return len(re.findall(r"\S+", normalized))


def reference_identity(reference: Any | None) -> str:
    if reference is None:
        return "none"
    encoded = json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_json_strings(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_ws(value)
    if isinstance(value, list):
        return [_normalize_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_json_strings(item) for key, item in value.items()}
    return value


def intent_reference_identity(intent_reference: Any | None) -> str:
    if not intent_reference:
        return "none"
    normalized = _normalize_json_strings(intent_reference)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def perturbation_identity(perturbations: list[str] | None) -> str:
    if not perturbations:
        return "none"
    normalized = [normalize_ws(item) for item in perturbations]
    return sha256_text(json.dumps(normalized, separators=(",", ":"), ensure_ascii=True))


def formal_properties_identity(properties: list[str] | None) -> str:
    return perturbation_identity(properties)
