import json

from syvern.sft.instruction_aug import (
    AugmentationConfig,
    TeacherCandidate,
    build_augmented_records,
    output_sha256,
    parse_teacher_payload,
    select_sample_records,
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
