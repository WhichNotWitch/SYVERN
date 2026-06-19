from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from syvern.models import Mode, ValidateResponse
from syvern.robustness import semantic_pass


@dataclass(frozen=True)
class ValidationRecord:
    sample_id: str
    text_hash: str
    mode: Mode
    validator_fingerprint: str
    cache_hit: bool
    semantic_pass: bool
    t0_pass: bool
    t1_available: bool
    veto_triggered: bool
    veto_reason: str | None
    requirement_coverage: float
    stable_at_k: float | None
    reward: float
    latency_ms: int
    prompt_id: str | None
    formal_evaluated: bool
    formal_status: str | None
    metadata: dict[str, str]


class InMemoryValidationRecordStore:
    def __init__(self, retention_limit: int | None = None) -> None:
        self.retention_limit = retention_limit
        self._records: list[ValidationRecord] = []

    def add(self, record: ValidationRecord) -> None:
        self._records.append(record)
        if self.retention_limit is not None and len(self._records) > self.retention_limit:
            del self._records[: len(self._records) - self.retention_limit]

    def list(self) -> list[ValidationRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()


class SQLiteValidationRecordStore:
    def __init__(self, path: str | Path, retention_limit: int | None = None) -> None:
        self.path = Path(path)
        self.retention_limit = retention_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add(self, record: ValidationRecord) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO validation_records (
                        sample_id, text_hash, mode, validator_fingerprint, cache_hit,
                        semantic_pass, t0_pass, t1_available, veto_triggered, veto_reason,
                        requirement_coverage, stable_at_k, reward, latency_ms, prompt_id,
                        formal_evaluated, formal_status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.sample_id,
                        record.text_hash,
                        record.mode,
                        record.validator_fingerprint,
                        int(record.cache_hit),
                        int(record.semantic_pass),
                        int(record.t0_pass),
                        int(record.t1_available),
                        int(record.veto_triggered),
                        record.veto_reason,
                        record.requirement_coverage,
                        record.stable_at_k,
                        record.reward,
                        record.latency_ms,
                        record.prompt_id,
                        int(record.formal_evaluated),
                        record.formal_status,
                        json.dumps(record.metadata, sort_keys=True),
                    ),
                )
                self._enforce_retention(connection)

    def list(self) -> list[ValidationRecord]:
        with closing(self._connect()) as connection:
            with connection:
                rows = connection.execute(
                    """
                    SELECT
                        sample_id, text_hash, mode, validator_fingerprint, cache_hit,
                        semantic_pass, t0_pass, t1_available, veto_triggered, veto_reason,
                        requirement_coverage, stable_at_k, reward, latency_ms, prompt_id,
                        formal_evaluated, formal_status, metadata_json
                    FROM validation_records
                    ORDER BY id
                    """
                ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def clear(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM validation_records")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS validation_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sample_id TEXT NOT NULL,
                        text_hash TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        validator_fingerprint TEXT NOT NULL,
                        cache_hit INTEGER NOT NULL,
                        semantic_pass INTEGER NOT NULL,
                        t0_pass INTEGER NOT NULL,
                        t1_available INTEGER NOT NULL,
                        veto_triggered INTEGER NOT NULL,
                        veto_reason TEXT,
                        requirement_coverage REAL NOT NULL,
                        stable_at_k REAL,
                        reward REAL NOT NULL,
                        latency_ms INTEGER NOT NULL,
                        prompt_id TEXT,
                        formal_evaluated INTEGER NOT NULL,
                        formal_status TEXT,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )

    def _enforce_retention(self, connection: sqlite3.Connection) -> None:
        if self.retention_limit is None:
            return
        connection.execute(
            """
            DELETE FROM validation_records
            WHERE id NOT IN (
                SELECT id
                FROM validation_records
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self.retention_limit,),
        )

    def _record_from_row(self, row: tuple) -> ValidationRecord:
        return ValidationRecord(
            sample_id=row[0],
            text_hash=row[1],
            mode=row[2],
            validator_fingerprint=row[3],
            cache_hit=bool(row[4]),
            semantic_pass=bool(row[5]),
            t0_pass=bool(row[6]),
            t1_available=bool(row[7]),
            veto_triggered=bool(row[8]),
            veto_reason=row[9],
            requirement_coverage=row[10],
            stable_at_k=row[11],
            reward=row[12],
            latency_ms=row[13],
            prompt_id=row[14],
            formal_evaluated=bool(row[15]),
            formal_status=row[16],
            metadata=json.loads(row[17]),
        )


def make_validation_record(
    response: ValidateResponse,
    *,
    metadata: dict[str, str] | None,
) -> ValidationRecord:
    metadata_payload = dict(metadata or {})
    prompt_id = metadata_payload.get("prompt_id")
    return ValidationRecord(
        sample_id=response.sample_id,
        text_hash=response.meta.text_hash,
        mode=response.meta.mode,
        validator_fingerprint=response.meta.validator_fingerprint,
        cache_hit=response.meta.cache_hit,
        semantic_pass=semantic_pass(response),
        t0_pass=response.tier_summary.t0_pass,
        t1_available=response.tier_summary.t1_available,
        veto_triggered=response.veto.triggered,
        veto_reason=response.veto.reason,
        requirement_coverage=response.structural.requirement_coverage if response.structural.evaluated else 0.0,
        stable_at_k=response.robustness.stable_at_k,
        reward=response.meta.reward,
        latency_ms=response.meta.latency_ms,
        prompt_id=prompt_id,
        formal_evaluated=response.formal.evaluated,
        formal_status=response.formal.status,
        metadata=metadata_payload,
    )
