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


def test_load_alignment_cases_accepts_manual_bool_schema(tmp_path):
    dataset = tmp_path / "manual.jsonl"
    dataset.write_text(
        "\n".join(
            [
                '{"case_id":"valid","category":"valid","text":"part vehicle.engine",'
                '"parse_ok":true,"resolve_ok":true,"typecheck_ok":true,"keep_expected":true}',
                '{"case_id":"syntax","category":"syntax","text":"syntax_error",'
                '"parse_ok":false,"resolve_ok":null,"typecheck_ok":null,"keep_expected":false}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_alignment_cases(dataset)

    assert cases[0] == AlignmentCase(
        case_id="valid",
        text="part vehicle.engine",
        parse_ok=True,
        category="valid",
        resolve_ok=True,
        typecheck_ok=True,
    )
    assert cases[1] == AlignmentCase(
        case_id="syntax",
        text="syntax_error",
        parse_ok=False,
        category="syntax",
        resolve_ok=None,
        typecheck_ok=None,
    )


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


def test_run_adapter_alignment_compares_manual_bool_stage_truth():
    cases = [
        AlignmentCase(
            case_id="valid",
            text="part vehicle.engine attribute vehicle.mass",
            parse_ok=True,
            category="valid",
            resolve_ok=True,
            typecheck_ok=True,
        ),
        AlignmentCase(
            case_id="syntax",
            text="syntax_error",
            parse_ok=False,
            category="syntax",
            resolve_ok=None,
            typecheck_ok=None,
        ),
        AlignmentCase(
            case_id="unresolved",
            text="unresolved_ref",
            parse_ok=True,
            category="unresolved",
            resolve_ok=False,
            typecheck_ok=None,
        ),
        AlignmentCase(
            case_id="type",
            text="part vehicle.engine type_error",
            parse_ok=True,
            category="type",
            resolve_ok=True,
            typecheck_ok=False,
        ),
    ]

    summary = run_adapter_alignment(PilotStubAdapter(), cases)

    assert summary.parse_accuracy == 1.0
    assert summary.resolve_accuracy == 1.0
    assert summary.typecheck_accuracy == 1.0
    assert summary.overall_accuracy == 1.0
    assert summary.failures == []


CORPUS = Path(__file__).resolve().parents[1] / "data" / "alignment" / "pilot_corpus.jsonl"


def test_element_accuracy_counts_only_labelled_cases():
    cases = [
        AlignmentCase(
            case_id="labelled",
            text="part vehicle.engine attribute vehicle.mass",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="valid",
            expected_elements=(("part", "vehicle.engine"), ("attribute", "vehicle.mass")),
        ),
        AlignmentCase(
            case_id="unlabelled",
            text="part vehicle.body",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="valid",
        ),
    ]

    summary = run_adapter_alignment(PilotStubAdapter(), cases)

    assert summary.element_labelled == 1
    assert summary.element_accuracy == 1.0


def test_element_mismatch_is_reported_and_lowers_overall():
    cases = [
        AlignmentCase(
            case_id="wrong-elements",
            text="part vehicle.engine",
            parse_ok=True,
            unresolved_refs=0,
            type_errors=0,
            category="valid",
            expected_elements=(("part", "vehicle.gearbox"),),
        )
    ]

    summary = run_adapter_alignment(PilotStubAdapter(), cases)

    assert summary.element_accuracy == 0.0
    assert summary.overall_accuracy == 0.0
    assert [f.stage for f in summary.failures] == ["elements"]


def test_pilot_corpus_meets_acceptance_gate():
    cases = load_alignment_cases(CORPUS)

    assert len(cases) >= 50
    assert {case.category for case in cases} == {
        "valid",
        "syntax_error",
        "unresolved_ref",
        "type_error",
        "nested_scale",
    }
    assert all(case.expected_elements is not None for case in cases)

    summary = run_adapter_alignment(PilotStubAdapter(), cases)

    assert summary.element_labelled == len(cases)
    assert summary.parse_accuracy == 1.0
    assert summary.resolve_accuracy == 1.0
    assert summary.typecheck_accuracy == 1.0
    assert summary.element_accuracy == 1.0
    assert summary.overall_accuracy == 1.0


REAL_CORPUS = Path(__file__).resolve().parents[1] / "data" / "alignment" / "pilot_real_corpus.jsonl"


def test_real_corpus_is_well_formed_for_the_real_adapter():
    # This corpus is CALIBRATED against the real Pilot 0.59.0 (labels = real Pilot
    # output) for `--adapter pilot`. It is NOT run against the stub here; we only
    # assert structure, labels, and that the content is genuinely SysML v2.
    cases = load_alignment_cases(REAL_CORPUS)

    assert len(cases) >= 40
    assert {case.category for case in cases} == {
        "valid",
        "syntax_error",
        "unresolved_ref",
        "type_error",
        "behavior",
    }
    assert all(case.expected_elements is not None for case in cases)
    # genuine SysML v2 syntax with real `::` qualified names
    assert all("part def" in case.text or "package" in case.text for case in cases)
    assert any("::" in element[1] for case in cases for element in case.expected_elements)
    for case in cases:
        if case.category == "syntax_error":
            assert case.parse_ok is False
        if case.category == "valid":
            assert case.parse_ok is True and case.unresolved_refs == 0 and case.type_errors == 0
        if case.category == "unresolved_ref":
            assert case.parse_ok is True and case.unresolved_refs >= 1
        if case.category == "type_error":
            assert case.parse_ok is True and case.type_errors >= 1


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
