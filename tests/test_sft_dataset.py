import json

from syvern.sft_dataset import (
    SourceSpec,
    build_sft_candidates,
    coverage_counts,
    dedupe_by_output,
    split_by_source_file,
)


def test_build_sft_candidates_from_sysml_files_records_source_and_constructs(tmp_path):
    source_root = tmp_path / "sysml-v2-release"
    example = source_root / "sysml" / "src" / "examples" / "Vehicle.sysml"
    example.parent.mkdir(parents=True)
    example.write_text(
        "package VehicleExample { part def Vehicle { port power; state def Mode { state off; } } }",
        encoding="utf-8",
    )
    ignored = source_root / "sysml" / "src" / "examples" / "Notes.txt"
    ignored.write_text("not sysml", encoding="utf-8")

    records = build_sft_candidates(
        [SourceSpec(root=source_root, repo="Systems-Modeling/SysML-v2-Release", commit="abc123", license="EPL-2.0")]
    )

    assert len(records) == 1
    record = records[0]
    assert record["id"].startswith("official_")
    assert record["instruction"] == (
        "Write a SysML v2 model covering package, part, port, and state constructs."
    )
    assert record["input"] == ""
    assert record["output"].startswith("package VehicleExample")
    assert record["constructs"] == ["package", "part", "port", "state"]
    assert record["source"] == {
        "repo": "Systems-Modeling/SysML-v2-Release",
        "commit": "abc123",
        "path": "sysml/src/examples/Vehicle.sysml",
        "license": "EPL-2.0",
    }


def test_dedupe_by_output_keeps_first_record_and_coverage_counts_constructs():
    records = [
        {"id": "a", "output": "package A { part def P; }", "constructs": ["package", "part"]},
        {"id": "b", "output": " package A {   part def P; } ", "constructs": ["package", "part"]},
        {"id": "c", "output": "package C { state def S { state idle; } }", "constructs": ["package", "state"]},
    ]

    deduped, duplicate_ids = dedupe_by_output(records)

    assert [record["id"] for record in deduped] == ["a", "c"]
    assert duplicate_ids == ["b"]
    assert coverage_counts(deduped) == {"package": 2, "part": 1, "state": 1}


def test_split_by_source_file_keeps_same_file_out_of_both_splits():
    records = [
        {"id": "a1", "source": {"path": "a.sysml"}, "output": "a1"},
        {"id": "a2", "source": {"path": "a.sysml"}, "output": "a2"},
        {"id": "b1", "source": {"path": "b.sysml"}, "output": "b1"},
        {"id": "c1", "source": {"path": "c.sysml"}, "output": "c1"},
    ]

    train, val = split_by_source_file(records, val_ratio=0.34)

    train_paths = {record["source"]["path"] for record in train}
    val_paths = {record["source"]["path"] for record in val}
    assert train_paths.isdisjoint(val_paths)
    assert len(train) + len(val) == len(records)
    assert val


def test_seed_jsonl_records_can_be_merged_with_official_candidates(tmp_path):
    source_root = tmp_path / "src"
    model = source_root / "Example.sysml"
    model.parent.mkdir(parents=True)
    model.write_text("package Example { part def P; }", encoding="utf-8")
    seed = tmp_path / "seed.jsonl"
    seed.write_text(
        json.dumps(
            {
                "id": "seed_port",
                "instruction": "Write a SysML v2 model with a port.",
                "input": "",
                "output": "package Seed { part def P { port p; } }",
                "constructs": ["package", "part", "port"],
                "source": {"repo": "local-seed", "commit": "manual", "path": "seed.jsonl", "license": "project"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = build_sft_candidates(
        [SourceSpec(root=source_root, repo="official", commit="abc", license="EPL-2.0")],
        seed_paths=[seed],
    )

    assert records[0]["id"].startswith("official_")
    assert records[1]["id"] == "seed_port"
