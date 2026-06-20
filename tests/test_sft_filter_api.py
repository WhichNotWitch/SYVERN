from syvern.sft_filter_api import filter_records_with_validate_batch


def test_filter_records_with_validate_batch_partitions_records_and_reports_rates():
    records = [
        {"id": "good", "output": "package Good { part def P; }"},
        {"id": "bad", "output": "package Bad { part def P :> ScalarValues::Integer; }"},
    ]
    calls = []

    def fake_validate_batch(texts):
        calls.append(texts)
        return {
            "responses": [
                {
                    "meta": {
                        "data_filter_pass": True,
                        "data_filter_reason": "passed",
                        "validator_fingerprint": "fp",
                        "reward": 0.9,
                    },
                    "sample_id": "s-good",
                },
                {
                    "meta": {
                        "data_filter_pass": False,
                        "data_filter_reason": "t0_failed",
                        "validator_fingerprint": "fp",
                        "reward": 0.5,
                    },
                    "sample_id": "s-bad",
                },
            ]
        }

    result = filter_records_with_validate_batch(records, fake_validate_batch, batch_size=8)

    assert calls == [["package Good { part def P; }", "package Bad { part def P :> ScalarValues::Integer; }"]]
    assert [record["id"] for record in result.kept] == ["good"]
    assert [record["id"] for record in result.rejected] == ["bad"]
    assert result.kept[0]["_syvern"]["validator_fingerprint"] == "fp"
    assert result.rejected[0]["_syvern"]["reason"] == "t0_failed"
    assert result.summary == {
        "read": 2,
        "passed": 1,
        "rejected": 1,
        "pass_rate": 0.5,
        "reason_counts": {"passed": 1, "t0_failed": 1},
        "validator_fingerprint": "fp",
    }


def test_filter_records_with_validate_batch_rejects_unexpected_fingerprint():
    records = [{"id": "good", "output": "package Good { part def P; }"}]

    def fake_validate_batch(texts):
        return {
            "responses": [
                {
                    "meta": {
                        "data_filter_pass": True,
                        "data_filter_reason": "passed",
                        "validator_fingerprint": "different",
                        "reward": 0.9,
                    },
                    "sample_id": "s-good",
                }
            ]
        }

    try:
        filter_records_with_validate_batch(records, fake_validate_batch, expected_fingerprint="fp")
    except ValueError as exc:
        assert "unexpected validator fingerprint" in str(exc)
    else:
        raise AssertionError("expected fingerprint mismatch")
