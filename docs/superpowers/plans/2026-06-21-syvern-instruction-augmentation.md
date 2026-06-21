# SYVERN Instruction Augmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested instruction-side augmentation pipeline that generates bilingual natural instructions for existing verified SFT outputs without mutating the source datasets.

**Architecture:** Add a focused `syvern.sft.instruction_aug` module for selection, teacher parsing, checks, record construction, reports, and orchestration. Add a thin script wrapper in `scripts/augment_sft_instructions.py` that reads environment variables, calls an OpenAI-compatible chat-completions endpoint, and writes sample or split-specific derived JSONL files.

**Tech Stack:** Python 3.11+, stdlib JSON/HTTP utilities, existing `syvern.sft.exporter.write_jsonl` / `write_json`, pytest with fake teacher clients for unit tests.

---

### Task 1: Core Augmentation Utilities

**Files:**
- Create: `src/syvern/sft/instruction_aug.py`
- Test: `tests/test_instruction_aug.py`

- [ ] **Step 1: Write failing utility tests**

Add tests covering parent hashing, teacher JSON parsing, deterministic sample selection, and checked augmented record construction:

```python
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
    assert output_sha256("package A { part def P; }") == output_sha256("package A { part def P; }")


def test_parse_teacher_payload_accepts_strict_candidates():
    payload = json.dumps(
        {
            "instructions": [
                {"variant": "zh_task", "language": "zh", "instruction": "用 SysML v2 建模 Vehicle，并包含 power 端口。"},
                {"variant": "zh_structural", "language": "zh", "instruction": "定义 Vehicle 部件并声明 power 端口。"},
                {"variant": "en_task", "language": "en", "instruction": "Create a SysML v2 model for a Vehicle with a power port."},
            ]
        },
        ensure_ascii=False,
    )

    candidates = parse_teacher_payload(payload)

    assert [candidate.variant for candidate in candidates] == ["zh_task", "zh_structural", "en_task"]
    assert candidates[0].language == "zh"


def test_select_sample_records_is_deterministic_and_covers_constructs():
    records = [
        _parent("part", "package A { part def P; }"),
        {**_parent("state", "package B { state def S { state idle; } }"), "constructs": ["package", "state"]},
        {**_parent("action", "package C { action def A; }"), "constructs": ["package", "action"]},
    ]

    selected = select_sample_records(records, limit=2)

    assert [record["id"] for record in selected] == ["part", "state"]


def test_build_augmented_records_preserves_parent_output_and_metadata():
    parent = _parent()
    candidates = [
        TeacherCandidate("zh_task", "zh", "用 SysML v2 建模 Vehicle，并包含 power 端口。"),
        TeacherCandidate("zh_structural", "zh", "定义 Vehicle 部件并声明 power 端口。"),
        TeacherCandidate("en_task", "en", "Create a SysML v2 model for a Vehicle with a power port."),
    ]
    config = AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1")

    augmented, failures = build_augmented_records(parent, candidates, config=config, batch_id="sample")

    assert failures == []
    assert len(augmented) == 3
    assert all(record["output"] == parent["output"] for record in augmented)
    assert augmented[0]["instruction"] == candidates[0].instruction
    assert augmented[0]["_syvern_instruction_aug"]["augmented_from"] == "p1"
    assert augmented[0]["_syvern_instruction_aug"]["teacher_base_url_host"] == "example.test"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: FAIL during import because `syvern.sft.instruction_aug` does not exist.

- [ ] **Step 3: Implement minimal utility module**

Create `src/syvern/sft/instruction_aug.py` with dataclasses for configuration and candidates, strict JSON parsing, deterministic sample selection, output hashing, and record construction that copies the parent output exactly.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: PASS.

### Task 2: Deterministic Quality Checks And Reports

**Files:**
- Modify: `src/syvern/sft/instruction_aug.py`
- Modify: `tests/test_instruction_aug.py`

- [ ] **Step 1: Write failing checker and report tests**

Add tests for rejection reasons, warnings, sibling duplicate detection, and report summaries:

```python
from syvern.sft.instruction_aug import (
    summarize_augmentation,
)


def test_checker_rejects_leakage_phrases_and_invalid_language():
    parent = _parent()
    config = AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1")
    candidates = [
        TeacherCandidate("zh_task", "zh", "请复制 the code below 并输出完全相同的模型。"),
        TeacherCandidate("en_task", "fr", "Create a SysML v2 model for Vehicle."),
    ]

    augmented, failures = build_augmented_records(parent, candidates, config=config, batch_id="sample")

    assert augmented == []
    assert {failure["reason"] for failure in failures} == {"forbidden_phrase", "invalid_language"}


def test_checker_rejects_identifier_names_not_present_in_output():
    parent = _parent()
    config = AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1")
    candidates = [TeacherCandidate("en_task", "en", "Create a SysML v2 model for AircraftController.")]

    augmented, failures = build_augmented_records(parent, candidates, config=config, batch_id="sample")

    assert augmented == []
    assert failures[0]["reason"] == "unsupported_identifier"


def test_checker_rejects_duplicate_sibling_instructions():
    parent = _parent()
    config = AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1")
    candidates = [
        TeacherCandidate("zh_task", "zh", "用 SysML v2 建模 Vehicle，并包含 power 端口。"),
        TeacherCandidate("zh_structural", "zh", "用   SysML v2 建模 Vehicle，并包含 power 端口。"),
    ]

    augmented, failures = build_augmented_records(parent, candidates, config=config, batch_id="sample")

    assert len(augmented) == 1
    assert failures[0]["reason"] == "duplicate_instruction"


def test_summary_counts_language_variants_and_failures():
    parent = _parent()
    config = AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1")
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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: FAIL because check failures and report summarization are missing or incomplete.

- [ ] **Step 3: Implement checker and report logic**

Extend `instruction_aug.py` with deterministic checks for empty text, length bounds, forbidden leakage phrases, invalid variant, invalid language, duplicate sibling instructions, unsupported identifiers, output hash preservation, and report summaries.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: PASS.

### Task 3: Pipeline Orchestration With Fake Teacher

**Files:**
- Modify: `src/syvern/sft/instruction_aug.py`
- Modify: `tests/test_instruction_aug.py`

- [ ] **Step 1: Write failing orchestration tests**

Add tests for sample trial generation and split-preserving full generation using a fake teacher:

```python
from pathlib import Path

from syvern.sft.instruction_aug import run_instruction_augmentation


class FakeTeacher:
    def generate(self, record):
        name = record["id"]
        return [
            TeacherCandidate("zh_task", "zh", f"用 SysML v2 建模 {name} 中的 Vehicle 和 power 端口。"),
            TeacherCandidate("zh_structural", "zh", f"定义 {name} 的 Vehicle 部件并声明 power 端口。"),
            TeacherCandidate("en_task", "en", f"Create a SysML v2 model for {name} with a Vehicle power port."),
        ]


def _write_jsonl(path: Path, records):
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def test_run_instruction_augmentation_sample_writes_jsonl_and_report(tmp_path):
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    _write_jsonl(train, [_parent("TrainVehicle")])
    _write_jsonl(val, [_parent("ValVehicle")])

    result = run_instruction_augmentation(
        train_path=train,
        val_path=val,
        output_dir=tmp_path / "instruction_aug",
        mode="sample",
        teacher=FakeTeacher(),
        config=AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"),
        sample_limit=1,
    )

    assert result.report["source_count"] == 1
    rows = [json.loads(line) for line in (tmp_path / "instruction_aug" / "sample_aug.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert rows[0]["_syvern_instruction_aug"]["batch_id"] == "sample"


def test_run_instruction_augmentation_full_preserves_train_val_splits(tmp_path):
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    _write_jsonl(train, [_parent("TrainVehicle")])
    _write_jsonl(val, [_parent("ValVehicle")])

    run_instruction_augmentation(
        train_path=train,
        val_path=val,
        output_dir=tmp_path / "instruction_aug",
        mode="full",
        teacher=FakeTeacher(),
        config=AugmentationConfig(teacher_model="gpt-5.5", teacher_base_url="https://example.test/v1"),
    )

    train_rows = [json.loads(line) for line in (tmp_path / "instruction_aug" / "train_aug.jsonl").read_text(encoding="utf-8").splitlines()]
    val_rows = [json.loads(line) for line in (tmp_path / "instruction_aug" / "val_aug.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["_syvern_instruction_aug"]["augmented_from"] for row in train_rows} == {"TrainVehicle"}
    assert {row["_syvern_instruction_aug"]["augmented_from"] for row in val_rows} == {"ValVehicle"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: FAIL because `run_instruction_augmentation` is not implemented.

- [ ] **Step 3: Implement orchestration**

Add JSONL loading, teacher iteration, sample/full mode output naming, complete report writing, and `AugmentationRunResult`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: PASS.

### Task 4: CLI Script And Documentation

**Files:**
- Create: `scripts/augment_sft_instructions.py`
- Modify: `data/sft/README.md`
- Test: `tests/test_instruction_aug.py`

- [ ] **Step 1: Write failing script configuration test**

Add a test for environment-based teacher configuration without making network calls:

```python
from scripts.augment_sft_instructions import config_from_env


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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: FAIL because `scripts/augment_sft_instructions.py` does not exist.

- [ ] **Step 3: Implement script**

Create an argparse script with `--mode sample|full`, `--train`, `--val`, `--out-dir`, `--sample-limit`, and `--batch-id`. Implement a stdlib `OpenAICompatibleTeacher` that posts to `{OPENAI_BASE_URL}/chat/completions` and parses the returned assistant content with `parse_teacher_payload`.

- [ ] **Step 4: Update README**

Add a short instruction augmentation section to `data/sft/README.md` with PowerShell environment variable setup using placeholder values only, sample command, full command, and the security note that API keys must not be committed or logged.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: PASS.

### Task 5: Verification And Sample Trial

**Files:**
- Generated: `data/sft/instruction_aug/sample_aug.jsonl`
- Generated: `data/sft/instruction_aug/reports/sample_report.json`

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_instruction_aug.py -v`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest`

Expected: PASS.

- [ ] **Step 3: Run sample trial when teacher environment is available**

Run:

```powershell
python scripts\augment_sft_instructions.py `
  --mode sample `
  --train data\sft\train.jsonl `
  --val data\sft\val.jsonl `
  --out-dir data\sft\instruction_aug `
  --sample-limit 20 `
  --batch-id sample
```

Expected: `sample_aug.jsonl` and `reports/sample_report.json` are written. If provider access fails, record the failure and do not fabricate generated data.

- [ ] **Step 4: Inspect generated sample quality**

Run:

```powershell
Get-Content -TotalCount 9 data\sft\instruction_aug\sample_aug.jsonl
Get-Content -Raw data\sft\instruction_aug\reports\sample_report.json
```

Expected: Outputs show bilingual natural instructions, copied SysML outputs, and a report with accepted/rejected counts.
