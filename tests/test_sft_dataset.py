import json

from syvern.sft_dataset import (
    SourceSpec,
    build_sft_candidates,
    coverage_counts,
    decompose_records,
    dedupe_by_output,
    split_by_source_file,
    split_top_level_packages,
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


def test_build_sft_candidates_merge_by_folder_concatenates_one_record_per_folder(tmp_path):
    source_root = tmp_path / "src"
    folder = source_root / "examples" / "VehicleExample"
    folder.mkdir(parents=True)
    # Two files in one folder where one imports the other — only valid together.
    (folder / "Defs.sysml").write_text("package Defs { part def Engine; }", encoding="utf-8")
    (folder / "Usage.sysml").write_text(
        "package Usage { import Defs::*; part def Vehicle { part engine : Engine; } }",
        encoding="utf-8",
    )
    other = source_root / "examples" / "Other"
    other.mkdir(parents=True)
    (other / "A.sysml").write_text("package A { part def P; }", encoding="utf-8")

    records = build_sft_candidates(
        [SourceSpec(root=source_root, repo="official", commit="abc", license="EPL-2.0")],
        merge_by_folder=True,
    )

    # One record per folder, not per file.
    assert len(records) == 2
    by_path = {record["source"]["path"]: record for record in records}
    vehicle = by_path["examples/VehicleExample"]
    assert "package Defs" in vehicle["output"] and "package Usage" in vehicle["output"]
    assert vehicle["source"]["files"] == [
        "examples/VehicleExample/Defs.sysml",
        "examples/VehicleExample/Usage.sysml",
    ]
    assert by_path["examples/Other"]["output"] == "package A { part def P; }"


def test_split_top_level_packages_brace_matches_and_skips_comment_braces():
    text = (
        'package A { part def P; // trailing } brace in comment\n'
        " /* block } brace */ }\n"
        'package B { attribute s = "literal } brace"; }'
    )
    blocks = split_top_level_packages(text)
    assert len(blocks) == 2
    assert blocks[0].startswith("package A {") and blocks[0].rstrip().endswith("}")
    assert blocks[1].startswith("package B {")


def test_decompose_records_emits_self_contained_passing_subpackages():
    record = {
        "id": "official_x",
        "output": "package Good { part def P; }\n\npackage NeedsSibling { part p : P; }",
        "source": {"path": "examples/Demo", "repo": "r"},
    }
    # Validator: a package passes only if it does not reference external 'P'.
    def validator(text: str) -> bool:
        return "part p : P" not in text

    seen: set[str] = set()
    new, report = decompose_records([record], validator, seen_outputs=seen, min_chars=10)

    assert report["tested"] == 2 and report["passed"] == 1 and report["added"] == 1
    assert len(new) == 1
    rec = new[0]
    assert rec["id"].startswith("decomp_")
    assert rec["output"] == "package Good { part def P; }"
    assert rec["source"]["decomposed_from"] == "official_x"
    assert rec["source"]["path"] == "examples/Demo"  # parent split group preserved
    assert rec["constructs"] == ["package", "part"]


def test_decompose_records_skips_already_seen_outputs():
    record = {"id": "o", "output": "package A { part def P; }\n\npackage B { item def I; }"}
    seen = {" ".join("package A { part def P; }".split())}
    new, report = decompose_records([record], lambda t: True, seen_outputs=seen, min_chars=10)
    # A is already seen; only B is emitted.
    assert [r["output"] for r in new] == ["package B { item def I; }"]


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
