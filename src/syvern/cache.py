from __future__ import annotations

import copy
import json
import sqlite3
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class CacheKey:
    text_hash: str
    validator_fingerprint: str
    mode: str
    reference_id: str
    perturbation_id: str = "none"
    intent_reference_id: str = "none"
    formal_properties_id: str = "none"


class InMemoryValidationCache:
    def __init__(self, max_size: int = 1024) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._items: OrderedDict[CacheKey, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(item)

    def set(self, key: CacheKey, value: dict[str, Any]) -> None:
        if not key.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
        with self._lock:
            self._items[key] = copy.deepcopy(value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class SQLiteValidationCache:
    def __init__(self, path: str | Path, max_size: int = 1024) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self._lock = RLock()
        self._clock = 0
        self._initialize()

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        """
                        SELECT payload_json
                        FROM validation_cache
                        WHERE key_json = ?
                        """,
                        (self._key_json(key),),
                    ).fetchone()
                    if row is None:
                        return None
                    connection.execute(
                        "UPDATE validation_cache SET last_access = ? WHERE key_json = ?",
                        (self._next_tick(), self._key_json(key)),
                    )
            return copy.deepcopy(json.loads(row[0]))

    def set(self, key: CacheKey, value: dict[str, Any]) -> None:
        if not key.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
        payload_json = json.dumps(copy.deepcopy(value), sort_keys=True)
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO validation_cache (key_json, payload_json, last_access)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key_json) DO UPDATE SET
                            payload_json = excluded.payload_json,
                            last_access = excluded.last_access
                        """,
                        (self._key_json(key), payload_json, self._next_tick()),
                    )
                    self._evict_over_capacity(connection)

    def clear(self) -> None:
        with self._lock:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("DELETE FROM validation_cache")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS validation_cache (
                        key_json TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        last_access INTEGER NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    "SELECT COALESCE(MAX(last_access), 0) FROM validation_cache"
                ).fetchone()
                self._clock = int(row[0])

    def _next_tick(self) -> int:
        self._clock += 1
        return self._clock

    def _evict_over_capacity(self, connection: sqlite3.Connection) -> None:
        overflow = connection.execute(
            "SELECT COUNT(*) - ? FROM validation_cache",
            (self.max_size,),
        ).fetchone()[0]
        if overflow <= 0:
            return
        connection.execute(
            """
            DELETE FROM validation_cache
            WHERE key_json IN (
                SELECT key_json
                FROM validation_cache
                ORDER BY last_access ASC
                LIMIT ?
            )
            """,
            (overflow,),
        )

    def _key_json(self, key: CacheKey) -> str:
        return json.dumps(
            {
                "text_hash": key.text_hash,
                "validator_fingerprint": key.validator_fingerprint,
                "mode": key.mode,
                "reference_id": key.reference_id,
                "perturbation_id": key.perturbation_id,
                "intent_reference_id": key.intent_reference_id,
                "formal_properties_id": key.formal_properties_id,
            },
            sort_keys=True,
        )
