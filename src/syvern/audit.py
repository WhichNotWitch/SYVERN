from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import sqlite3
from contextlib import closing
import json
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.request import Request, urlopen


AuditOutcome = Literal["allowed", "denied"]


@dataclass(frozen=True)
class AuditEvent:
    method: str
    path: str
    required_permission: str
    outcome: AuditOutcome
    reason: str | None
    token_present: bool
    token_role: str | None
    tenant_id: str | None
    auth_method: Literal["token", "identity"] | None = None
    principal_id: str | None = None
    principal_groups: tuple[str, ...] = ()


class InMemoryAuditEventStore:
    def __init__(self, retention_limit: int = 1000) -> None:
        self.retention_limit = retention_limit
        self._events: deque[AuditEvent] = deque(maxlen=retention_limit)
        self._lock = RLock()

    def add(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class SQLiteAuditEventStore:
    def __init__(self, path: str | Path, retention_limit: int | None = None) -> None:
        self.path = Path(path)
        self.retention_limit = retention_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add(self, event: AuditEvent) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        method, path, required_permission, outcome, reason,
                        token_present, token_role, tenant_id,
                        auth_method, principal_id, principal_groups_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.method,
                        event.path,
                        event.required_permission,
                        event.outcome,
                        event.reason,
                        int(event.token_present),
                        event.token_role,
                        event.tenant_id,
                        event.auth_method,
                        event.principal_id,
                        json.dumps(list(event.principal_groups), sort_keys=True),
                    ),
                )
                self._enforce_retention(connection)

    def list(self) -> list[AuditEvent]:
        with closing(self._connect()) as connection:
            with connection:
                rows = connection.execute(
                    """
                    SELECT method, path, required_permission, outcome, reason,
                           token_present, token_role, tenant_id,
                           auth_method, principal_id, principal_groups_json
                    FROM audit_events
                    ORDER BY id
                    """
                ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def clear(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("DELETE FROM audit_events")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        method TEXT NOT NULL,
                        path TEXT NOT NULL,
                        required_permission TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        reason TEXT,
                        token_present INTEGER NOT NULL,
                        token_role TEXT,
                        tenant_id TEXT,
                        auth_method TEXT,
                        principal_id TEXT,
                        principal_groups_json TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
                existing_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
                }
                if "auth_method" not in existing_columns:
                    connection.execute("ALTER TABLE audit_events ADD COLUMN auth_method TEXT")
                if "principal_id" not in existing_columns:
                    connection.execute("ALTER TABLE audit_events ADD COLUMN principal_id TEXT")
                if "principal_groups_json" not in existing_columns:
                    connection.execute(
                        "ALTER TABLE audit_events ADD COLUMN principal_groups_json TEXT NOT NULL DEFAULT '[]'"
                    )

    def _enforce_retention(self, connection: sqlite3.Connection) -> None:
        if self.retention_limit is None:
            return
        connection.execute(
            """
            DELETE FROM audit_events
            WHERE id NOT IN (
                SELECT id
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self.retention_limit,),
        )

    def _event_from_row(self, row: tuple) -> AuditEvent:
        return AuditEvent(
            method=row[0],
            path=row[1],
            required_permission=row[2],
            outcome=row[3],
            reason=row[4],
            token_present=bool(row[5]),
            token_role=row[6],
            tenant_id=row[7],
            auth_method=row[8],
            principal_id=row[9],
            principal_groups=tuple(json.loads(row[10])),
        )


class HTTPAuditEventSink:
    def __init__(self, endpoint: str, timeout_s: float = 2.0) -> None:
        self.endpoint = endpoint
        self.timeout_s = timeout_s

    def add(self, event: AuditEvent) -> None:
        payload = json.dumps(_event_payload(event), sort_keys=True).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s):
            return


def _event_payload(event: AuditEvent) -> dict[str, object]:
    return {
        "method": event.method,
        "path": event.path,
        "required_permission": event.required_permission,
        "outcome": event.outcome,
        "reason": event.reason,
        "token_present": event.token_present,
        "token_role": event.token_role,
        "tenant_id": event.tenant_id,
        "auth_method": event.auth_method,
        "principal_id": event.principal_id,
        "principal_groups": list(event.principal_groups),
    }
