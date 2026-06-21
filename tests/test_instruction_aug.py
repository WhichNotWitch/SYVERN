import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.augment_sft_instructions import config_from_env
from syvern.sft.instruction_aug import (
    AugmentationConfig,
    TeacherCandidate,
    build_augmented_records,
    output_sha256,
    parse_teacher_payload,
    run_instruction_augmentation,
    select_sample_records,
    summarize_augmentation,
)


def _parent(record_id="p1", output="package VehicleModel { part def Vehicle { port power; } }"):
    return {
        "id": record_id,
        "instruction": "Write a SysML v2 model covering package, part, and port constructs.",
        "input": "",
        "output": output,
        "constructs": ["package", "part", "port"],
        "source": {"repo": "local", "path": "seed"},
        "_syvern": {"pass": True, "validator_fingerprint": "fp"},
    }


class FakeTeacher:
    def generate(self, record):
        return [
            TeacherCandidate(
                "zh_task",
                "zh",
                f"用 SysML v2 建模 {record['id']} 中的 Vehicle 和 power 端口。",
            ),
            TeacherCandidate(
                "zh_structural",
                "zh",
                f"定义 {record['id']} 的 Vehicle 部件并声明 power 端口。",
            ),
            TeacherCandidate(
                "en_task",
                "en",
                f"Create a SysML v2 model for {record['id']} with a Vehicle power port.",
            ),
        ]


def _write_jsonl(path: Path, records):
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def test_output_sha256_is_stable_for_parent_output():
    assert output_sha256("package A { part def P; }") == output_sha256(
        "package A { part def P; }"
    )


def test_parse_teacher_payload_accepts_strict_candidates():
    payload = json.dumps(
        {
            "instructions": [
                {
                    "variant": "zh_task",
                    "language": "zh",
                    "instruction": "用 SysML v2 建模 Vehicle，并包含 power 端口。",
                },
                {
                    "variant": "zh_structural",
                    "language": "zh",
                    "instruction": "定义 Vehicle 部件并声明 power 端口。",
                },
                {
                    "variant": "en_task",
                    "language": "en",
                    "instruction": "Create a SysML v2 model for a Vehicle with a power port.",
                },
            ]
        },
        ensure_ascii=False,
    )

    candidates = parse_teacher_payload(payload)

    assert [candidate.variant for candidate in candidates] == [
        "zh_task",
        "zh_structural",
        "en_task",
    ]
    assert candidates[0].language == "zh"


def test_select_sample_records_is_deterministic_and_covers_constructs():
    records = [
        _parent("part", "package A { part def P; }"),
        {
            **_parent("state", "package B { state def S { state idle; } }"),
            "constructs": ["package", "state"],
        },
        {
            **_parent("action", "package C { action def A; }"),
            "constructs": ["package", "action"],
        },
    ]

    selected = select_sample_records(records, limit=2)

    assert [record["id"] for record in selected] == ["part", "state"]


def test_build_augmented_records_preserves_parent_output_and_metadata():
    parent = _parent()
    candidates = [
        TeacherCandidate("zh_task", "zh", "用 SysML v2 建模 Vehicle，并包含 power 端口。"),
        TeacherCandidate("zh_structural", "zh", "定义 Vehicle 部件并声明 power 端口。"),
        TeacherCandidate(
            "en_task", "en", "Create a SysML v2 model for a Vehicle with a power port."
        ),
    ]
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )

    augmented, failures = build_augmented_records(
        parent, candidates, config=config, batch_id="sample"
    )

    assert failures == []
    assert len(augmented) == 3
    assert all(record["output"] == parent["output"] for record in augmented)
    assert augmented[0]["instruction"] == candidates[0].instruction
    assert augmented[0]["_syvern_instruction_aug"]["augmented_from"] == "p1"
    assert augmented[0]["_syvern_instruction_aug"]["teacher_base_url_host"] == "example.test"


def test_checker_rejects_leakage_phrases_and_invalid_language():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    candidates = [
        TeacherCandidate("zh_task", "zh", "请复制 the code below 并输出完全相同的模型。"),
        TeacherCandidate("en_task", "fr", "Create a SysML v2 model for Vehicle."),
    ]

    augmented, failures = build_augmented_records(
        parent, candidates, config=config, batch_id="sample"
    )

    assert augmented == []
    assert {failure["reason"] for failure in failures} == {
        "forbidden_phrase",
        "invalid_language",
    }


def test_checker_rejects_identifier_names_not_present_in_output():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    candidates = [
        TeacherCandidate("en_task", "en", "Create a SysML v2 model for AircraftController.")
    ]

    augmented, failures = build_augmented_records(
        parent, candidates, config=config, batch_id="sample"
    )

    assert augmented == []
    assert failures[0]["reason"] == "unsupported_identifier"


def test_checker_allows_identifier_substrings_present_in_output():
    parent = _parent(
        "official_arrowhead",
        "package AHFNorway { part def APISConsumer; } package AHFNorwaySequences { action transfer; }",
    )
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    candidates = [
        TeacherCandidate(
            "en_task",
            "en",
            "Create a SysML v2 model for the Norway use case.",
        )
    ]

    augmented, failures = build_augmented_records(
        parent, candidates, config=config, batch_id="sample"
    )

    assert failures == []
    assert len(augmented) == 1


def test_checker_rejects_english_instruction_over_word_limit():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    long_instruction = (
        "Create a SysML v2 model for Vehicle with power ports and parts that "
        "also describes extra modeling context repeatedly so this request has "
        "more than forty five words while still mentioning only lowercase terms "
        "and names that appear in the verified target output VehicleModel "
        "Vehicle power VehicleModel Vehicle power VehicleModel."
    )

    augmented, failures = build_augmented_records(
        parent,
        [TeacherCandidate("en_task", "en", long_instruction)],
        config=config,
        batch_id="sample",
    )

    assert augmented == []
    assert failures[0]["reason"] == "invalid_length"


def test_checker_rejects_duplicate_sibling_instructions():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    candidates = [
        TeacherCandidate("zh_task", "zh", "用 SysML v2 建模 Vehicle，并包含 power 端口。"),
        TeacherCandidate("zh_structural", "zh", "用   SysML v2 建模 Vehicle，并包含 power 端口。"),
    ]

    augmented, failures = build_augmented_records(
        parent, candidates, config=config, batch_id="sample"
    )

    assert len(augmented) == 1
    assert failures[0]["reason"] == "duplicate_instruction"


def test_summary_counts_language_variants_and_failures():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )
    augmented, failures = build_augmented_records(
        parent,
        [
            TeacherCandidate("zh_task", "zh", "用 SysML v2 建模 Vehicle，并包含 power 端口。"),
            TeacherCandidate("en_task", "fr", "Create a SysML v2 model for Vehicle."),
        ],
        config=config,
        batch_id="sample",
    )

    report = summarize_augmentation(source_count=1, augmented=augmented, failures=failures)

    assert report["source_count"] == 1
    assert report["accepted_count"] == 1
    assert report["rejected_count"] == 1
    assert report["language_counts"] == {"zh": 1}
    assert report["failure_reason_counts"] == {"invalid_language": 1}


def test_checker_warns_for_generic_instruction_with_low_identifier_overlap():
    parent = _parent()
    config = AugmentationConfig(
        teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
    )

    augmented, failures = build_augmented_records(
        parent,
        [TeacherCandidate("en_task", "en", "Write a SysML v2 model with parts and ports.")],
        config=config,
        batch_id="sample",
    )

    assert failures == []
    assert augmented[0]["_syvern_instruction_aug"]["checks"]["warnings"] == [
        "low_identifier_overlap"
    ]


def test_run_instruction_augmentation_sample_writes_jsonl_and_report(tmp_path):
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    _write_jsonl(train, [_parent("Vehicle")])
    _write_jsonl(val, [_parent("VehicleModel")])

    result = run_instruction_augmentation(
        train_path=train,
        val_path=val,
        output_dir=tmp_path / "instruction_aug",
        mode="sample",
        teacher=FakeTeacher(),
        config=AugmentationConfig(
            teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
        ),
        sample_limit=1,
    )

    assert result.report["source_count"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "instruction_aug" / "sample_aug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 3
    assert rows[0]["_syvern_instruction_aug"]["batch_id"] == "sample"
    assert (tmp_path / "instruction_aug" / "reports" / "sample_report.json").exists()


def test_run_instruction_augmentation_full_preserves_train_val_splits(tmp_path):
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    _write_jsonl(train, [_parent("Vehicle")])
    _write_jsonl(val, [_parent("VehicleModel")])

    run_instruction_augmentation(
        train_path=train,
        val_path=val,
        output_dir=tmp_path / "instruction_aug",
        mode="full",
        teacher=FakeTeacher(),
        config=AugmentationConfig(
            teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"
        ),
    )

    train_rows = [
        json.loads(line)
        for line in (tmp_path / "instruction_aug" / "train_aug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    val_rows = [
        json.loads(line)
        for line in (tmp_path / "instruction_aug" / "val_aug.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {row["_syvern_instruction_aug"]["augmented_from"] for row in train_rows} == {
        "Vehicle"
    }
    assert {row["_syvern_instruction_aug"]["augmented_from"] for row in val_rows} == {
        "VehicleModel"
    }


def test_config_from_env_requires_teacher_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SYVERN_TEACHER_MODEL", raising=False)

    try:
        config_from_env()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("config_from_env should exit when teacher env is missing")


def test_config_from_env_reads_non_secret_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("SYVERN_TEACHER_MODEL", "gpt-5.5")

    config = config_from_env()

    assert config.teacher_model == "gpt-5.5"
    assert config.teacher_base_url == "https://example.test/v1"


def test_script_direct_invocation_reaches_environment_validation():
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_BASE_URL", None)
    env.pop("SYVERN_TEACHER_MODEL", None)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/augment_sft_instructions.py",
            "--mode",
            "sample",
            "--train",
            "data/sft/train.jsonl",
            "--val",
            "data/sft/val.jsonl",
            "--out-dir",
            "data/sft/instruction_aug",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "missing required environment variable" in result.stderr
