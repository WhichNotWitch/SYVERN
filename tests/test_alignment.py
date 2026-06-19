from pathlib import Path

from syvern.adapters.stub import PilotStubAdapter
from syvern.alignment import AlignmentCase, load_alignment_cases, run_adapter_alignment


DATASET = Path(__file__).resolve().parents[1] / "data" / "alignment" / "stub_smoke.jsonl"


def test_load_alignment_cases_from_jsonl():
    cases = load_alignment_cases(DATASET)

    assert cases[0] == AlignmentCase(
        case_id="valid-basic",
        text="part vehicle.engine attribute vehicle.mass",
        parse_ok=True,
        unresolved_refs=0,
        type_errors=0,
        category="valid",
    )
    assert {case.case_id for case in cases} == {
        "valid-basic",
        "syntax-error",
        "unresolved-ref",
        "type-error",
    }


def test_run_adapter_alignment_reports_stage_accuracy_and_failures():
    cases = [
        AlignmentCase(
            case_id="valid-basic",
            text="part vehicle.engine attribute vehicle.mass",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="valid",
        ),
        AlignmentCase(
            case_id="syntax",
            text="syntax_error",
            parse_ok=False,
            unresolved_refs=0,
            type_errors=0,
            category="syntax_error",
        ),
        AlignmentCase(
            case_id="bad-expectation",
            text="part vehicle.engine type_error",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="type_error",
        ),
    ]

    summary = run_adapter_alignment(PilotStubAdapter(), cases)

    assert summary.adapter_fingerprint == "pilot-stub@0.6.0"
    assert summary.total == 3
    assert summary.category_counts == {"syntax_error": 1, "type_error": 1, "valid": 1}
    assert summary.parse_accuracy == 1.0
    assert summary.resolve_accuracy == 1.0
    assert summary.typecheck_accuracy == 2 / 3
    assert summary.overall_accuracy == 2 / 3
    assert len(summary.failures) == 1
    assert summary.failures[0].case_id == "bad-expectation"
    assert summary.failures[0].stage == "typecheck"
    assert summary.failures[0].expected == "0"
    assert summary.failures[0].actual == "1"


def test_load_alignment_cases_defaults_missing_category_to_unspecified(tmp_path):
    dataset = tmp_path / "alignment.jsonl"
    dataset.write_text(
        '{"case_id":"legacy","text":"part A attribute x","parse_ok":true,"unresolved_refs":0,"type_errors":0}\n',
        encoding="utf-8",
    )

    cases = load_alignment_cases(dataset)

    assert cases == [
        AlignmentCase(
            case_id="legacy",
            text="part A attribute x",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="unspecified",
        )
    ]
