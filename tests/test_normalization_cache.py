from pathlib import Path
from uuid import uuid4

from syvern.cache import CacheKey, InMemoryValidationCache
from syvern.cache import SQLiteValidationCache
from syvern.normalization import intent_reference_identity
from syvern.normalization import perturbation_identity, reference_identity, sha256_text, token_count
from syvern.settings import SyvernSettings


def test_text_hash_normalizes_whitespace():
    left = sha256_text("part   A\n\nattribute x")
    right = sha256_text("part A attribute x")
    assert left == right


def test_token_count_uses_normalized_words():
    assert token_count("  part   A\nattribute x  ") == 4


def test_reference_identity_is_stable_for_nested_dicts():
    left = reference_identity({"b": 2, "a": {"x": 1}})
    right = reference_identity({"a": {"x": 1}, "b": 2})
    assert left == right


def test_perturbation_identity_normalizes_whitespace_and_preserves_order():
    first = perturbation_identity([" part A ", "attribute   x"])
    second = perturbation_identity(["part A", "attribute x"])
    reversed_items = perturbation_identity(["attribute x", "part A"])

    assert first == second
    assert first != reversed_items


def test_perturbation_identity_treats_missing_and_empty_as_none():
    assert perturbation_identity(None) == "none"
    assert perturbation_identity([]) == "none"


def test_cache_key_includes_mode_and_reference_identity():
    settings = SyvernSettings()
    text_hash = sha256_text("part A attribute x")
    ref_id = reference_identity({"name": "reference"})
    online = CacheKey(text_hash, settings.validator_fingerprint, "online_reward", ref_id)
    full = CacheKey(text_hash, settings.validator_fingerprint, "full", ref_id)
    assert online != full


def test_cache_returns_stored_response_by_exact_key():
    cache = InMemoryValidationCache()
    key = CacheKey("abc", "fingerprint", "online_reward", "none")
    payload = {"sample_id": "sample-abc"}
    cache.set(key, payload)
    assert cache.get(key) == payload


def test_cache_get_isolates_nested_validation_payloads():
    cache = InMemoryValidationCache()
    key = CacheKey("abc", "fingerprint", "online_reward", "none")
    payload = {
        "sample_id": "sample-abc",
        "meta": {"cache_hit": False},
    }
    cache.set(key, payload)

    cached = cache.get(key)
    assert cached is not None
    cached["meta"]["cache_hit"] = True

    assert cache.get(key)["meta"]["cache_hit"] is False


def test_cache_evicts_least_recently_used_item_when_capacity_is_exceeded():
    cache = InMemoryValidationCache(max_size=2)
    first = CacheKey("first", "fingerprint", "online_reward", "none")
    second = CacheKey("second", "fingerprint", "online_reward", "none")
    third = CacheKey("third", "fingerprint", "online_reward", "none")

    cache.set(first, {"sample_id": "first"})
    cache.set(second, {"sample_id": "second"})
    cache.set(third, {"sample_id": "third"})

    assert cache.get(first) is None
    assert cache.get(second) == {"sample_id": "second"}
    assert cache.get(third) == {"sample_id": "third"}


def test_cache_get_refreshes_lru_recency():
    cache = InMemoryValidationCache(max_size=2)
    first = CacheKey("first", "fingerprint", "online_reward", "none")
    second = CacheKey("second", "fingerprint", "online_reward", "none")
    third = CacheKey("third", "fingerprint", "online_reward", "none")

    cache.set(first, {"sample_id": "first"})
    cache.set(second, {"sample_id": "second"})
    assert cache.get(first) == {"sample_id": "first"}
    cache.set(third, {"sample_id": "third"})

    assert cache.get(first) == {"sample_id": "first"}
    assert cache.get(second) is None
    assert cache.get(third) == {"sample_id": "third"}


def test_cache_rejects_non_positive_capacity():
    for max_size in (0, -1):
        try:
            InMemoryValidationCache(max_size=max_size)
        except ValueError as exc:
            assert "max_size must be positive" in str(exc)
        else:
            raise AssertionError("expected invalid cache capacity to raise")


def test_intent_reference_identity_normalizes_nested_string_whitespace():
    left = intent_reference_identity(
        {
            "must_include": [" vehicle.engine ", "vehicle.  mass"],
            "requirements": ["model   engine"],
        }
    )
    right = intent_reference_identity(
        {
            "requirements": ["model engine"],
            "must_include": ["vehicle.engine", "vehicle. mass"],
        }
    )

    assert left == right


def test_intent_reference_identity_treats_missing_and_empty_as_none():
    assert intent_reference_identity(None) == "none"
    assert intent_reference_identity({}) == "none"


def test_cache_key_includes_intent_reference_identity():
    base = CacheKey("abc", "fingerprint", "full", "ref", "pert", "intent-a")
    changed_intent = CacheKey("abc", "fingerprint", "full", "ref", "pert", "intent-b")

    assert base != changed_intent


def test_sqlite_cache_persists_payloads_across_instances():
    db_path = Path(".pytest_tmp") / f"cache-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    key = CacheKey("abc", "fingerprint", "full", "ref", "pert", "intent", "formal")
    payload = {"sample_id": "sample-abc", "meta": {"cache_hit": False}}

    try:
        cache = SQLiteValidationCache(db_path)
        cache.set(key, payload)
        payload["meta"]["cache_hit"] = True

        reopened = SQLiteValidationCache(db_path)
        cached = reopened.get(key)
        assert cached == {"sample_id": "sample-abc", "meta": {"cache_hit": False}}

        cached["meta"]["cache_hit"] = True
        assert reopened.get(key)["meta"]["cache_hit"] is False
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_cache_isolates_validator_fingerprint_and_clears():
    db_path = Path(".pytest_tmp") / f"cache-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    key = CacheKey("abc", "fingerprint-a", "online_reward", "none")
    changed_fingerprint = CacheKey("abc", "fingerprint-b", "online_reward", "none")

    try:
        cache = SQLiteValidationCache(db_path)
        cache.set(key, {"sample_id": "sample-abc"})

        assert cache.get(changed_fingerprint) is None
        cache.clear()
        assert SQLiteValidationCache(db_path).get(key) is None
    finally:
        db_path.unlink(missing_ok=True)


def test_sqlite_cache_evicts_least_recently_used_item():
    db_path = Path(".pytest_tmp") / f"cache-{uuid4().hex}.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    first = CacheKey("first", "fingerprint", "online_reward", "none")
    second = CacheKey("second", "fingerprint", "online_reward", "none")
    third = CacheKey("third", "fingerprint", "online_reward", "none")

    try:
        cache = SQLiteValidationCache(db_path, max_size=2)
        cache.set(first, {"sample_id": "first"})
        cache.set(second, {"sample_id": "second"})
        assert cache.get(first) == {"sample_id": "first"}
        cache.set(third, {"sample_id": "third"})

        assert cache.get(first) == {"sample_id": "first"}
        assert cache.get(second) is None
        assert cache.get(third) == {"sample_id": "third"}
    finally:
        db_path.unlink(missing_ok=True)
