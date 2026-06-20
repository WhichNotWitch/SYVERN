import json

import pytest

from syvern.cli import _adapter, main


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _fake_passing_pilot_urlopen(request, timeout):
    if request.full_url.endswith("/version"):
        return _FakeResponse({"pilot_version": "realv"})
    return _FakeResponse(
        {
            "parse": {"ok": True, "errors": []},
            "resolve": {"ok": True, "unresolved_refs": 0, "errors": []},
            "typecheck": {"ok": True, "type_errors": 0, "errors": []},
            "elements": [
                {"type": "part", "qualified_name": "vehicle.engine"},
                {"type": "attribute", "qualified_name": "vehicle.mass"},
            ],
        }
    )


def test_adapter_pilot_builds_http_adapter_from_env(monkeypatch):
    from syvern.adapters.pilot import PilotAdapter

    monkeypatch.setenv("SYVERN_PILOT_ENDPOINT", "http://pilot.local:8888")
    monkeypatch.setenv("SYVERN_PILOT_VERSION", "2026.9")

    adapter = _adapter("pilot")

    assert isinstance(adapter, PilotAdapter)
    assert adapter.endpoint == "http://pilot.local:8888"
    assert adapter.version == "2026.9"


def test_adapter_pilot_defaults_to_local_8888(monkeypatch):
    monkeypatch.delenv("SYVERN_PILOT_ENDPOINT", raising=False)

    adapter = _adapter("pilot")

    assert adapter.endpoint == "http://127.0.0.1:8888"


def test_alignment_cli_runs_against_real_pilot_adapter(monkeypatch, tmp_path, capsys):
    validate_payload = {
        "parse": {"ok": True, "errors": []},
        "resolve": {"ok": True, "unresolved_refs": 0, "errors": []},
        "typecheck": {"ok": True, "type_errors": 0, "errors": []},
        "elements": [
            {"type": "part", "qualified_name": "P::V"},
            {"type": "attribute", "qualified_name": "P::V::m"},
        ],
    }

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/version"):
            return _FakeResponse({"pilot_version": "realv"})
        return _FakeResponse(validate_payload)

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    monkeypatch.setenv("SYVERN_PILOT_ENDPOINT", "http://pilot.local")

    dataset = tmp_path / "real.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "v",
                "category": "valid",
                "text": "package P { part def V { attribute m; } }",
                "parse_ok": True,
                "unresolved_refs": 0,
                "type_errors": 0,
                "expected_elements": [
                    {"type": "part", "qualified_name": "P::V"},
                    {"type": "attribute", "qualified_name": "P::V::m"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        ["align", "--adapter", "pilot", "--dataset", str(dataset), "--min-element-accuracy", "1.0"]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["adapter_name"] == "pilot"
    assert output["adapter_fingerprint"] == "pilot@realv"
    assert output["element_accuracy"] == 1.0
    assert output["overall_accuracy"] == 1.0


def test_alignment_cli_rejects_removed_adapter_names():
    with pytest.raises(SystemExit):
        main(["align", "--adapter", "pilot-stub", "--dataset", "data/alignment/stub_smoke.jsonl"])


def test_alignment_cli_emits_calibrated_corpus(monkeypatch, tmp_path, capsys):
    from syvern.alignment import load_alignment_cases

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", _fake_passing_pilot_urlopen)
    dataset = tmp_path / "in.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "c",
                "category": "valid",
                "text": "part vehicle.engine attribute vehicle.mass",
                "parse_ok": True,
                "unresolved_refs": 0,
                "type_errors": 0,
                "expected_elements": [{"type": "part", "qualified_name": "deliberately.wrong"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "calibrated.jsonl"

    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot",
            "--dataset",
            str(dataset),
            "--emit-calibrated",
            str(out),
            "--min-element-accuracy",
            "1.0",
        ]
    )

    # emit mode exits 0 even though the original labels fail the gate
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["element_accuracy"] == 0.0

    # the emitted corpus carries the adapter's actual (correct) labels
    calibrated = load_alignment_cases(out)
    assert calibrated[0].parse_ok is True
    assert calibrated[0].expected_elements == (
        ("part", "vehicle.engine"),
        ("attribute", "vehicle.mass"),
    )


def test_benchmark_cli_outputs_json_summary_for_sample_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("syvern.adapters.pilot.urlopen", _fake_passing_pilot_urlopen)
    samples = tmp_path / "samples.txt"
    samples.write_text(
        "\n".join(
            [
                "part vehicle.engine attribute vehicle.mass",
                "",
                "part vehicle.body connection vehicle.body_to_engine",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["benchmark", "--samples", str(samples)])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["sample_count"] == 2
    assert output["semantic_pass_count"] == 2
    assert output["average_latency_ms"] >= 0.0
    assert output["throughput_per_s"] > 0.0


def test_benchmark_cli_returns_nonzero_when_latency_threshold_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("syvern.adapters.pilot.urlopen", _fake_passing_pilot_urlopen)
    samples = tmp_path / "samples.txt"
    samples.write_text("part vehicle.engine attribute vehicle.mass\n", encoding="utf-8")

    exit_code = main(
        [
            "benchmark",
            "--samples",
            str(samples),
            "--max-average-latency-ms",
            "0.0",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["average_latency_ms"] > 0.0


def test_benchmark_cli_returns_nonzero_when_throughput_threshold_fails(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr("syvern.adapters.pilot.urlopen", _fake_passing_pilot_urlopen)
    samples = tmp_path / "samples.txt"
    samples.write_text("part vehicle.engine attribute vehicle.mass\n", encoding="utf-8")

    exit_code = main(
        [
            "benchmark",
            "--samples",
            str(samples),
            "--min-throughput-per-s",
            "1000000000.0",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["throughput_per_s"] < 1000000000.0


def _fake_pilot_urlopen_by_text(text_to_payload):
    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/version"):
            return _FakeResponse({"pilot_version": "realv"})
        body = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(text_to_payload[body["text"]])

    return fake_urlopen


_T0_PASS = {
    "parse": {"ok": True, "errors": []},
    "resolve": {"ok": True, "unresolved_refs": 0, "errors": []},
    "typecheck": {"ok": True, "type_errors": 0, "errors": []},
    "elements": [{"type": "part", "qualified_name": "p::v"}],
}
_T0_PARSE_FAIL = {
    "parse": {"ok": False, "errors": [{"code": "PILOT_SYNTAX_ERROR", "message": "boom"}]},
    "resolve": {"ok": False, "unresolved_refs": 0, "errors": []},
    "typecheck": {"ok": False, "type_errors": 0, "errors": []},
    "elements": [],
}


def test_filter_cli_partitions_corpus_and_writes_outputs(monkeypatch, tmp_path, capsys):
    good = "part def Good { part v; }"
    bad = "part def Bad {"
    monkeypatch.setattr(
        "syvern.adapters.pilot.urlopen",
        _fake_pilot_urlopen_by_text({good: _T0_PASS, bad: _T0_PARSE_FAIL}),
    )

    dataset = tmp_path / "corpus.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps({"id": "a", "text": good}),
                "",  # blank lines are ignored
                json.dumps({"id": "b", "text": bad}),
                json.dumps({"id": "c"}),  # missing text -> skipped
                "{not json",  # malformed -> skipped
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    kept = tmp_path / "kept.jsonl"
    rejected = tmp_path / "rejected.jsonl"

    exit_code = main(
        [
            "filter",
            "--dataset",
            str(dataset),
            "--output",
            str(kept),
            "--rejected",
            str(rejected),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["read"] == 4
    assert output["evaluated"] == 2
    assert output["passed"] == 1
    assert output["dropped"] == 1
    assert output["skipped"] == 2
    assert output["reason_counts"]["passed"] == 1
    assert output["reason_counts"]["t0_failed"] == 1
    assert output["reason_counts"]["missing_text"] == 1
    assert output["reason_counts"]["malformed_input"] == 1

    kept_records = [json.loads(line) for line in kept.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in kept_records] == ["a"]
    assert kept_records[0]["_syvern"]["pass"] is True
    assert kept_records[0]["_syvern"]["reason"] == "passed"

    rejected_ids = {
        json.loads(line).get("id") for line in rejected.read_text(encoding="utf-8").splitlines()
    }
    assert "b" in rejected_ids and "c" in rejected_ids


def test_filter_cli_min_keep_ratio_gate_fails(monkeypatch, tmp_path, capsys):
    bad = "part def Bad {"
    monkeypatch.setattr(
        "syvern.adapters.pilot.urlopen",
        _fake_pilot_urlopen_by_text({bad: _T0_PARSE_FAIL}),
    )
    dataset = tmp_path / "corpus.jsonl"
    dataset.write_text(json.dumps({"id": "b", "text": bad}) + "\n", encoding="utf-8")

    exit_code = main(
        ["filter", "--dataset", str(dataset), "--min-keep-ratio", "0.5"]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["keep_ratio"] == 0.0
