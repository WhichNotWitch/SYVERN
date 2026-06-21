import json

from syvern.coverage.schema import CoverageReport
from syvern.sft.normalizer import normalize_sft_record
from syvern.sft.pipeline import run_sft_prepare
from syvern.sft.policy import decide_sft_keep


class _Stage:
    def __init__(self, ok: bool) -> None:
        self.ok = ok


class _Veto:
    def __init__(self, triggered: bool) -> None:
        self.triggered = triggered


class _Meta:
    def __init__(self) -> None:
        self.validator_fingerprint = "test-fingerprint"
        self.reward = 0.9


class _ValidationResult:
    def __init__(self, *, parse=True, resolve=True, typecheck=True, veto=False) -> None:
        self.stage = type(
            "Stage",
            (),
            {
                "parse": _Stage(parse),
                "resolve": _Stage(resolve),
                "typecheck": _Stage(typecheck),
            },
        )()
        self.veto = _Veto(veto)
        self.sample_id = "validation-sample"
        self.meta = _Meta()


def test_normalize_sft_record_maps_instruction_input_output_to_internal_sample():
    sample = normalize_sft_record(
        {
            "id": "sample_001",
            "instruction": "Write SysML.",
            "input": "ObstacleDetected shall trigger EmergencyStopping.",
            "output": "state def Train { accept ObstacleDetected; state EmergencyStopping; }",
            "source": "llm_synthetic",
            "task_type": "nl_to_sysml",
            "coverage_spec": {"required": ["ObstacleDetected", "EmergencyStopping"]},
        }
    )

    assert sample.sample_id == "sample_001"
    assert sample.requirement_text == "ObstacleDetected shall trigger EmergencyStopping."
    assert sample.sysml_text.startswith("state def Train")
    assert sample.source == "llm_synthetic"
    assert sample.task_type == "nl_to_sysml"
    assert sample.metadata["coverage_spec"]["required"] == [
        "ObstacleDetected",
        "EmergencyStopping",
    ]


def test_decide_sft_keep_consumes_coverage_report_without_knowing_backend():
    validation = _ValidationResult()
    coverage = CoverageReport(
        sample_id="s1",
        backend="simple",
        score=0.5,
        passed=False,
        required_items=[],
        missing_items=["EmergencyStopping"],
        evidence_type="keyword_alias_match",
    )

    keep, reason = decide_sft_keep(validation, coverage, require_coverage=True, min_coverage=0.6)

    assert keep is False
    assert reason == "low_requirement_coverage"


def test_run_sft_prepare_outputs_kept_rejected_and_report(tmp_path):
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "processed"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "good",
                        "input": "ObstacleDetected shall trigger EmergencyStopping.",
                        "output": "state def Train { accept ObstacleDetected; state EmergencyStopping; }",
                        "coverage_spec": {
                            "required": ["ObstacleDetected", "EmergencyStopping"]
                        },
                    }
                ),
                json.dumps(
                    {
                        "id": "bad",
                        "input": "ObstacleDetected shall trigger EmergencyStopping.",
                        "output": "part def Train { attribute speed; }",
                        "coverage_spec": {
                            "required": ["ObstacleDetected", "EmergencyStopping"]
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_sft_prepare(
        input_path,
        output_dir,
        validator=lambda sample: _ValidationResult(),
        coverage_backend="simple",
        min_coverage=0.6,
    )

    assert result.summary["read"] == 2
    assert result.summary["kept"] == 1
    assert result.summary["rejected"] == 1
    assert result.summary["validator_fingerprint"] == "test-fingerprint"
    assert result.summary["reason_counts"] == {"low_requirement_coverage": 1, "passed": 1}
    kept = [json.loads(line) for line in (output_dir / "kept.jsonl").read_text(encoding="utf-8").splitlines()]
    rejected = [
        json.loads(line)
        for line in (output_dir / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert kept[0]["_syvern_sft"]["keep"] is True
    assert kept[0]["_syvern_sft"]["validator_fingerprint"] == "test-fingerprint"
    assert kept[0]["_syvern_sft"]["sample_id"] == "validation-sample"
    assert kept[0]["_syvern_sft"]["reward"] == 0.9
    assert kept[0]["_syvern_coverage"]["score"] == 1.0
    assert rejected[0]["_syvern_sft"]["reason"] == "low_requirement_coverage"


def test_run_sft_prepare_accepts_utf8_bom_jsonl(tmp_path):
    input_path = tmp_path / "input.jsonl"
    output_dir = tmp_path / "processed"
    input_path.write_text(
        '\ufeff{"id":"good","input":"ObstacleDetected","output":"ObstacleDetected"}\n',
        encoding="utf-8",
    )

    result = run_sft_prepare(
        input_path,
        output_dir,
        validator=lambda sample: _ValidationResult(),
        coverage_backend="none",
    )

    assert result.summary["kept"] == 1
