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


def test_adapter_pilot_builds_http_adapter_from_env(monkeypatch):
    from syvern.adapters.pilot import PilotAdapter

    monkeypatch.setenv("SYVERN_PILOT_ENDPOINT", "http://pilot.local:8080")
    monkeypatch.setenv("SYVERN_PILOT_VERSION", "2026.9")

    adapter = _adapter("pilot")

    assert isinstance(adapter, PilotAdapter)
    assert adapter.endpoint == "http://pilot.local:8080"
    assert adapter.version == "2026.9"


def test_adapter_pilot_requires_endpoint(monkeypatch):
    monkeypatch.delenv("SYVERN_PILOT_ENDPOINT", raising=False)

    with pytest.raises(SystemExit):
        _adapter("pilot")


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


def test_alignment_cli_outputs_json_summary_for_stub_dataset(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/stub_smoke.jsonl",
            "--min-overall",
            "1.0",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["adapter_name"] == "pilot-stub"
    assert output["total"] == 4
    assert output["category_counts"] == {
        "syntax_error": 1,
        "type_error": 1,
        "unresolved_ref": 1,
        "valid": 1,
    }
    assert output["overall_accuracy"] == 1.0
    assert output["failures"] == []


def test_alignment_cli_returns_nonzero_when_threshold_fails(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/stub_smoke.jsonl",
            "--min-overall",
            "1.1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["overall_accuracy"] == 1.0


def test_alignment_cli_returns_nonzero_when_stage_threshold_fails(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/stub_smoke.jsonl",
            "--min-overall",
            "1.0",
            "--min-parse",
            "1.1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["parse_accuracy"] == 1.0


def test_alignment_cli_returns_nonzero_when_min_cases_gate_fails(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/stub_smoke.jsonl",
            "--min-overall",
            "1.0",
            "--min-cases",
            "50",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["total"] == 4


def test_alignment_cli_returns_nonzero_when_required_category_is_missing(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/stub_smoke.jsonl",
            "--min-overall",
            "1.0",
            "--require-category",
            "valid",
            "--require-category",
            "nested_scale",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["category_counts"]["valid"] == 1
    assert "nested_scale" not in output["category_counts"]


def test_alignment_cli_enforces_element_accuracy_gate(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/pilot_corpus.jsonl",
            "--min-element-accuracy",
            "1.0",
            "--min-cases",
            "50",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["element_accuracy"] == 1.0
    assert output["element_labelled"] >= 50


def test_alignment_cli_returns_nonzero_when_element_accuracy_unmet(capsys):
    exit_code = main(
        [
            "align",
            "--adapter",
            "pilot-stub",
            "--dataset",
            "data/alignment/pilot_corpus.jsonl",
            "--min-element-accuracy",
            "1.1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["element_accuracy"] == 1.0


def test_alignment_cli_runs_subset_adapter_on_real_corpus(capsys):
    # In-process real validation: parse/resolve/elements on real SysML v2, no JVM.
    # The corpus is calibrated to the real Pilot; the subset agrees on SYNTAX
    # (parse) but its element/resolve labels differ, so only gate on parse.
    exit_code = main(
        [
            "align",
            "--adapter",
            "subset",
            "--dataset",
            "data/alignment/pilot_real_corpus.jsonl",
            "--min-overall",
            "0.0",
            "--min-parse",
            "1.0",
            "--min-cases",
            "20",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["adapter_name"] == "subset-pilot"
    # subset agrees with the real Pilot on syntax and intra-file resolution;
    # element sets differ (simpler extraction), so element accuracy is not gated.
    assert output["parse_accuracy"] == 1.0
    assert output["resolve_accuracy"] == 1.0


def test_alignment_cli_emits_calibrated_corpus(tmp_path, capsys):
    from syvern.alignment import load_alignment_cases

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
            "pilot-stub",
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


def test_benchmark_cli_outputs_json_summary_for_sample_file(tmp_path, capsys):
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


def test_benchmark_cli_returns_nonzero_when_latency_threshold_fails(tmp_path, capsys):
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


def test_benchmark_cli_returns_nonzero_when_throughput_threshold_fails(tmp_path, capsys):
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
