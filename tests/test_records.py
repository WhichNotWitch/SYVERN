from syvern.pipeline import ValidationPipeline
from syvern.records import InMemoryValidationRecordStore, make_validation_record


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
    assert record.metadata == {"domain": "vehicle"}


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


def test_record_store_returns_copy_of_records_list():
    store = InMemoryValidationRecordStore()
    record = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={})
    store.add(record)

    listed = store.list()
    listed.clear()

    assert store.list() == [record]
