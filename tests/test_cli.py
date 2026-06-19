import json

from syvern.cli import main


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
