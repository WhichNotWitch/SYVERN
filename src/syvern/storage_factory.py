from __future__ import annotations

from syvern.audit import HTTPAuditEventSink, InMemoryAuditEventStore, SQLiteAuditEventStore
from syvern.cache import InMemoryValidationCache, SQLiteValidationCache
from syvern.records import InMemoryValidationRecordStore, SQLiteValidationRecordStore
from syvern.settings import SyvernSettings


def build_validation_cache(settings: SyvernSettings) -> InMemoryValidationCache | SQLiteValidationCache:
    if settings.cache_path:
        return SQLiteValidationCache(settings.cache_path, max_size=settings.cache_max_size)
    return InMemoryValidationCache(max_size=settings.cache_max_size)


def build_validation_record_store(
    settings: SyvernSettings,
) -> InMemoryValidationRecordStore | SQLiteValidationRecordStore:
    if settings.record_store_path:
        return SQLiteValidationRecordStore(
            settings.record_store_path,
            retention_limit=settings.record_retention_limit,
        )
    return InMemoryValidationRecordStore(retention_limit=settings.record_retention_limit)


def build_audit_event_store(settings: SyvernSettings) -> InMemoryAuditEventStore | SQLiteAuditEventStore:
    if settings.audit_log_path:
        return SQLiteAuditEventStore(
            settings.audit_log_path,
            retention_limit=settings.audit_retention_limit,
        )
    retention_limit = 1000 if settings.audit_retention_limit is None else settings.audit_retention_limit
    return InMemoryAuditEventStore(retention_limit=retention_limit)


def build_audit_event_sink(settings: SyvernSettings) -> HTTPAuditEventSink | None:
    if settings.audit_sink_endpoint is None:
        return None
    return HTTPAuditEventSink(settings.audit_sink_endpoint, timeout_s=settings.audit_sink_timeout_s)
