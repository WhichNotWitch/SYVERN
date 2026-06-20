from syvern.data_filter_gate import run_data_filter_gate_check
from syvern.pipeline import ValidationPipeline
from syvern.settings import SyvernSettings


def test_data_filter_gate_check_compares_keep_expected_with_pipeline_decision():
    records = [
        {
            "case_id": "valid",
            "text": "part vehicle.engine attribute vehicle.mass",
            "keep_expected": True,
        },
        {
            "case_id": "type",
            "text": "part vehicle.engine attribute vehicle.mass type_error",
            "keep_expected": False,
        },
    ]

    summary = run_data_filter_gate_check(ValidationPipeline(), records)

    assert summary.total == 2
    assert summary.matches == 2
    assert summary.accuracy == 1.0
    assert summary.failures == []


def test_data_filter_gate_check_reports_stage_policy_mismatches():
    records = [
        {
            "case_id": "type",
            "text": "part vehicle.engine attribute vehicle.mass type_error",
            "keep_expected": False,
        },
    ]
    pipeline = ValidationPipeline(settings=SyvernSettings(data_filter_min_stage="resolve"))

    summary = run_data_filter_gate_check(pipeline, records)

    assert summary.total == 1
    assert summary.matches == 0
    assert summary.accuracy == 0.0
    assert len(summary.failures) == 1
    assert summary.failures[0].case_id == "type"
    assert summary.failures[0].expected is False
    assert summary.failures[0].actual is True
    assert summary.failures[0].reason == "passed"
