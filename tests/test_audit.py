from pathlib import Path
from uuid import uuid4

from syvern.audit import AuditEvent, HTTPAuditEventSink, InMemoryAuditEventStore, SQLiteAuditEventStore


def _event(path: str = "/validate", outcome: str = "allowed") -> AuditEvent:
    return AuditEvent(
        method="POST",
        path=path,
        required_permission="write",
        outcome=outcome,
        reason=None if outcome == "allowed" else "insufficient_scope",
        token_present=True,
        token_role="write",
        tenant_id="tenant-a",
    )


def test_in_memory_audit_store_keeps_most_recent_events_when_bounded():
    store = InMemoryAuditEventStore(retention_limit=2)

    store.add(_event("/first"))
    store.add(_event("/second"))
    store.add(_event("/third"))

    assert [event.path for event in store.list()] == ["/second", "/third"]


def test_sqlite_audit_store_roundtrips_events_without_token_values():
    db_path = Path(".pytest_tmp") / f"audit-{uuid4().hex}.sqlite3"
    try:
        store = SQLiteAuditEventStore(db_path)
        store.add(_event("/monitor_summary"))

        reopened = SQLiteAuditEventStore(db_path)

        assert reopened.list() == [_event("/monitor_summary")]
        assert "write-token" not in repr(reopened.list())
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_audit_store_with_retention_limit_keeps_most_recent_events():
    db_path = Path(".pytest_tmp") / f"audit-{uuid4().hex}.sqlite3"
    try:
        store = SQLiteAuditEventStore(db_path, retention_limit=2)

        store.add(_event("/first"))
        store.add(_event("/second", outcome="denied"))
        store.add(_event("/third"))

        reopened = SQLiteAuditEventStore(db_path, retention_limit=2)
        assert [event.path for event in reopened.list()] == ["/second", "/third"]
        assert reopened.list()[0].outcome == "denied"
        assert reopened.list()[0].reason == "insufficient_scope"
    finally:
        db_path.unlink(missing_ok=True)


def test_http_audit_event_sink_posts_sanitized_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("syvern.audit.urlopen", fake_urlopen)
    sink = HTTPAuditEventSink("http://audit.local/events", timeout_s=1.5)

    sink.add(_event("/monitor_summary"))

    assert captured["url"] == "http://audit.local/events"
    assert captured["timeout"] == 1.5
    assert captured["headers"]["Content-type"] == "application/json"
    assert '"path": "/monitor_summary"' in captured["body"]
    assert '"token_present": true' in captured["body"]
    assert "token" in captured["body"]
    assert "write-token" not in captured["body"]
