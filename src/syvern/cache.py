from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CacheKey:
    text_hash: str
    validator_fingerprint: str
    mode: str
    reference_id: str


class InMemoryValidationCache:
    def __init__(self) -> None:
        self._items: dict[CacheKey, dict[str, Any]] = {}

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        item = self._items.get(key)
        if item is None:
            return None
        return copy.deepcopy(item)

    def set(self, key: CacheKey, value: dict[str, Any]) -> None:
        if not key.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
        self._items[key] = copy.deepcopy(value)

    def clear(self) -> None:
        self._items.clear()
