from syvern.cache import CacheKey, InMemoryValidationCache
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
