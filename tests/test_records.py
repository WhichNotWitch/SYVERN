from syvern.models import FormalSummary
from syvern.pipeline import ValidationPipeline
from pathlib import Path
from uuid import uuid4

from syvern.records import InMemoryValidationRecordStore, SQLiteValidationRecordStore, make_validation_record


def test_make_validation_record_extracts_h6_fields():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")
    response.meta.cache_hit = True

    record = make_validation_record(response, metadata={"domain": "vehicle"})

    assert record.sample_id == response.sample_id
    assert record.text_hash == response.meta.text_hash
    assert record.mode == "online_reward"
    assert record.validator_fingerprint == response.meta.validator_fingerprint
    assert record.cache_hit is True
    assert record.semantic_pass is True
    assert record.t0_pass is True
    assert record.t1_available is False
    assert record.veto_triggered is False
    assert record.veto_reason is None
    assert record.requirement_coverage == 0.0
    assert record.stable_at_k is None
    assert record.reward == response.meta.reward
    assert record.latency_ms == response.meta.latency_ms
    assert record.formal_evaluated is False
    assert record.formal_status is None
    assert record.metadata == {"domain": "vehicle"}


def test_make_validation_record_extracts_formal_status():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")
    response.formal = FormalSummary(
        evaluated=True,
        tool="imandra",
        status="proved",
        properties_checked=1,
    )

    record = make_validation_record(response, metadata=None)

    assert record.formal_evaluated is True
    assert record.formal_status == "proved"


def test_make_validation_record_defaults_missing_metadata_to_empty_dict():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")

    record = make_validation_record(response, metadata=None)

    assert record.metadata == {}


def test_make_validation_record_copies_metadata_snapshot():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")
    metadata = {"checkpoint": "a"}

    record = make_validation_record(response, metadata=metadata)
    metadata["checkpoint"] = "b"

    assert record.metadata == {"checkpoint": "a"}


def test_record_store_records_and_clears_events_in_order():
    store = InMemoryValidationRecordStore()
    first = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={"n": "1"})
    second = make_validation_record(ValidationPipeline().validate("part B unresolved_ref"), metadata={"n": "2"})

    store.add(first)
    store.add(second)

    assert store.list() == [first, second]
    store.clear()
    assert store.list() == []


def test_record_store_with_retention_limit_keeps_most_recent_events():
    store = InMemoryValidationRecordStore(retention_limit=2)
    first = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={"n": "1"})
    second = make_validation_record(ValidationPipeline().validate("part B attribute y"), metadata={"n": "2"})
    third = make_validation_record(ValidationPipeline().validate("part C attribute z"), metadata={"n": "3"})

    store.add(first)
    store.add(second)
    store.add(third)

    assert store.list() == [second, third]


def test_record_store_returns_copy_of_records_list():
    store = InMemoryValidationRecordStore()
    record = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={})
    store.add(record)

    listed = store.list()
    listed.clear()

    assert store.list() == [record]


def test_sqlite_record_store_persists_events_across_instances():
    db_path = Path(".pytest_tmp") / f"records-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    first = make_validation_record(
        ValidationPipeline().validate("part vehicle.engine attribute vehicle.mass"),
        metadata={"prompt_id": "prompt-a", "domain": "vehicle"},
    )
    second = make_validation_record(
        ValidationPipeline().validate("part vehicle.engine unresolved_ref"),
        metadata={"prompt_id": "prompt-b"},
    )

    try:
        store = SQLiteValidationRecordStore(db_path)
        store.add(first)
        store.add(second)

        reopened = SQLiteValidationRecordStore(db_path)

        assert reopened.list() == [first, second]
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_record_store_clear_removes_persisted_events():
    db_path = Path(".pytest_tmp") / f"records-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    record = make_validation_record(
        ValidationPipeline().validate("part vehicle.engine attribute vehicle.mass"),
        metadata={"checkpoint": "rft-001"},
    )

    try:
        store = SQLiteValidationRecordStore(db_path)
        store.add(record)
        store.clear()

        assert SQLiteValidationRecordStore(db_path).list() == []
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_record_store_with_retention_limit_keeps_most_recent_persisted_events():
    db_path = Path(".pytest_tmp") / f"records-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    first = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={"n": "1"})
    second = make_validation_record(ValidationPipeline().validate("part B attribute y"), metadata={"n": "2"})
    third = make_validation_record(ValidationPipeline().validate("part C attribute z"), metadata={"n": "3"})

    try:
        store = SQLiteValidationRecordStore(db_path, retention_limit=2)
        store.add(first)
        store.add(second)
        store.add(third)

        reopened = SQLiteValidationRecordStore(db_path, retention_limit=2)

        assert reopened.list() == [second, third]
    finally:
        db_path.unlink(missing_ok=True)
