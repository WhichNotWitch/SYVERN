from pathlib import Path
from uuid import uuid4

from syvern.audit import HTTPAuditEventSink, InMemoryAuditEventStore, SQLiteAuditEventStore
from syvern.cache import InMemoryValidationCache, SQLiteValidationCache
from syvern.records import InMemoryValidationRecordStore, SQLiteValidationRecordStore
from syvern.settings import SyvernSettings
from syvern.storage_factory import (
    build_audit_event_sink,
    build_audit_event_store,
    build_validation_cache,
    build_validation_record_store,
)


def test_build_validation_cache_uses_memory_by_default():
    cache = build_validation_cache(SyvernSettings())

    assert isinstance(cache, InMemoryValidationCache)


def test_build_validation_cache_uses_sqlite_when_path_is_configured():
    db_path = Path(".pytest_tmp") / f"cache-{uuid4().hex}.sqlite3"
    try:
        cache = build_validation_cache(SyvernSettings(cache_path=str(db_path), cache_max_size=7))

        assert isinstance(cache, SQLiteValidationCache)
        assert cache.path == db_path
        assert cache.max_size == 7
    finally:
        db_path.unlink(missing_ok=True)


def test_build_validation_record_store_uses_memory_by_default():
    store = build_validation_record_store(SyvernSettings())

    assert isinstance(store, InMemoryValidationRecordStore)


def test_build_validation_record_store_passes_retention_limit_to_memory_store():
    store = build_validation_record_store(SyvernSettings(record_retention_limit=7))

    assert isinstance(store, InMemoryValidationRecordStore)
    assert store.retention_limit == 7


def test_build_validation_record_store_uses_sqlite_when_path_is_configured():
    db_path = Path(".pytest_tmp") / f"records-{uuid4().hex}.sqlite3"
    try:
        store = build_validation_record_store(
            SyvernSettings(record_store_path=str(db_path), record_retention_limit=7)
        )

        assert isinstance(store, SQLiteValidationRecordStore)
        assert store.path == db_path
        assert store.retention_limit == 7
    finally:
        db_path.unlink(missing_ok=True)


def test_build_audit_event_store_uses_memory_by_default():
    store = build_audit_event_store(SyvernSettings())

    assert isinstance(store, InMemoryAuditEventStore)


def test_build_audit_event_store_passes_retention_limit_to_memory_store():
    store = build_audit_event_store(SyvernSettings(audit_retention_limit=7))

    assert isinstance(store, InMemoryAuditEventStore)
    assert store.retention_limit == 7


def test_build_audit_event_store_uses_sqlite_when_path_is_configured():
    db_path = Path(".pytest_tmp") / f"audit-{uuid4().hex}.sqlite3"
    try:
        store = build_audit_event_store(SyvernSettings(audit_log_path=str(db_path), audit_retention_limit=7))

        assert isinstance(store, SQLiteAuditEventStore)
        assert store.path == db_path
        assert store.retention_limit == 7
    finally:
        db_path.unlink(missing_ok=True)


def test_build_audit_event_sink_returns_none_by_default():
    assert build_audit_event_sink(SyvernSettings()) is None


def test_build_audit_event_sink_uses_http_when_endpoint_is_configured():
    sink = build_audit_event_sink(
        SyvernSettings(audit_sink_endpoint="http://audit.local/events", audit_sink_timeout_s=1.25)
    )

    assert isinstance(sink, HTTPAuditEventSink)
    assert sink.endpoint == "http://audit.local/events"
    assert sink.timeout_s == 1.25


def test_settings_rejects_non_positive_cache_capacity():
    try:
        SyvernSettings(cache_max_size=0)
    except ValueError as exc:
        assert str(exc) == "cache_max_size must be positive"
    else:
        raise AssertionError("expected invalid cache capacity to raise")


def test_settings_rejects_non_positive_record_retention_limit():
    try:
        SyvernSettings(record_retention_limit=0)
    except ValueError as exc:
        assert str(exc) == "record_retention_limit must be positive"
    else:
        raise AssertionError("expected invalid record retention limit to raise")


def test_settings_rejects_non_positive_audit_retention_limit():
    try:
        SyvernSettings(audit_retention_limit=0)
    except ValueError as exc:
        assert str(exc) == "audit_retention_limit must be positive"
    else:
        raise AssertionError("expected invalid audit retention limit to raise")
