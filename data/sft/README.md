# SYVERN SFT Dataset

This directory contains the Phase 2 starter SFT dataset built from official
SysML v2 sources plus a small local seed set.

## Source Policy

- Primary source: `Systems-Modeling/SysML-v2-Release`
- Source commit used for the current build:
  `ee25530ed24b8c93a0e3e4b8d5fbfaa5a8d8ffb4`
- License recorded for official examples and libraries: `EPL-2.0`
- Local supplemental seed: `data/sft/seed.jsonl`, license label `project`

Raw checkouts and intermediate files are intentionally ignored by git:

- `data/sft/raw_sources/`
- `data/sft/interim/`

## Rebuild

Pilot must run on `8888` **with the repo's own SysML library loaded** so the
examples' domain-library imports (`ShapeItems`, `SpatialItems`, `Quantities`,
`AnalysisTooling`, …) resolve — point `SYSML_LIBRARY_PATH` at
`data/sft/raw_sources/sysml-v2-release/sysml.library`. Start the SYVERN API on
`8000`, then run:

```powershell
git clone --depth 1 https://github.com/Systems-Modeling/SysML-v2-Release.git data\sft\raw_sources\sysml-v2-release

# Source root is sysml/src (examples + training + validation); the sysml.library
# tree is the loaded library, not training data, so it is excluded.
# --merge-by-folder (default on) treats each folder as one complete model: the
# official examples cross-import sibling files, so per-file validation wrongly
# fails resolve.
python scripts\prepare_sft_data.py `
  --source-root data\sft\raw_sources\sysml-v2-release\sysml\src `
  --repo Systems-Modeling/SysML-v2-Release `
  --license EPL-2.0 `
  --seed data\sft\seed.jsonl `
  --max-chars 80000 `
  --out data\sft\interim\candidates.jsonl `
  --report data\sft\reports\prepare_report.json

python scripts\validate_and_filter.py `
  --in data\sft\interim\candidates.jsonl `
  --kept data\sft\interim\filtered.jsonl `
  --rejected data\sft\interim\rejected.jsonl `
  --report data\sft\reports\filter_report.json `
  --endpoint http://127.0.0.1:8000 --batch-size 8 --timeout-s 180

python scripts\split_sft_data.py `
  --in data\sft\interim\filtered.jsonl `
  --train data\sft\train.jsonl `
  --val data\sft\val.jsonl `
  --report data\sft\reports\split_report.json
```

## Current Build

Folder-merged, with the repo's full SysML library loaded in Pilot:

- Candidates: 99 (83 official folders under `sysml/src` + 16 seed)
- Passed data filter (auto): 86 / Rejected: 13 (all `t0_failed`; 0 vetoed) → 86.9%
- The 13 rejects were **cross-chapter imports** (training/validation lessons that
  reference packages defined in earlier chapters). All 13 were **human-resolved**
  by prepending the imported dependency packages (import-closure) and re-pass the
  gate. Resolution provenance lives in each record's `source.human_resolution`.
- Kept full models (auto 86 + human-resolved 13): 99
- **Decomposition augmentation**: multi-package models are split into
  self-contained single-package sub-models, each re-validated standalone through
  the gate (`scripts/decompose_sft_data.py`). Decomposed train/val sub-models are
  deduped and kept in their parent's split (no leakage); each carries
  `source.decomposed_from`. Added: train +156, val +15.
- Validated models after decomposition: 270 (train 245 / val 25)
  (origin: 16 seed + 70 official folder-merged + 13 human-resolved + 171 decomposed)
- **Instruction augmentation**: a `gpt-5.5` teacher rewrites each model's
  instruction into 3 natural variants (`zh_task`, `zh_structural`, `en_task`)
  via `scripts/augment_sft_instructions.py`. **Output (code) is byte-identical to
  the validated parent** (verified: 0/810 drift) so it still passes the gate; only
  the instruction changes. The weak construct-list template instructions are
  dropped — each model now carries its 3 GPT-5.5 instructions. Provenance in
  `_syvern_instruction_aug` (teacher_model, parent_output_sha256, variant, …).
- **Final dataset: 810 records** — Train 735 / Val 75 (270 models × 3 instructions)
- Duplicate outputs: 0 · Train/val output overlap: 0 (augmentation is per-split)
- Construct coverage unchanged from the 270 validated models (code is identical).
- Re-validation: seed 16/16, train 735/735, val 75/75 pass the pinned fingerprint

All final records pass the pinned validator fingerprint:

```text
syvern-phase2-pilot-http@0.8.0+rules@h4+intent@heuristic-h5+ops@h6+match@h9-normalized-fuzzy-v1+backends[pilot@pilot-0.59.0,monticore-stub@0.6.0]
```

Reports:

- `reports/prepare_report.json`: source commit and construct coverage before filtering.
- `reports/filter_report.json`: data-filter pass rate and rejection reasons.
- `reports/split_report.json`: dedupe, train/val sizes, and construct coverage.
- `reports/train_filter_report.json` and `reports/val_filter_report.json`: final pass checks.

## Instruction Augmentation

Instruction-side augmentation keeps the verified SysML `output` text unchanged
and creates bilingual natural instructions for the same code. Generated records
are written under `data/sft/instruction_aug/`; the canonical `train.jsonl` and
`val.jsonl` files are not modified.

Set teacher-provider configuration through environment variables. Use a real API
key only in your local shell; do not commit it or paste it into reports.

```powershell
$env:OPENAI_API_KEY = "<your-api-key>"
$env:OPENAI_BASE_URL = "https://example.test/v1"
$env:SYVERN_TEACHER_MODEL = "gpt-5.5"
```

Run a small sample trial first:

```powershell
python scripts\augment_sft_instructions.py `
  --mode sample `
  --train data\sft\train.jsonl `
  --val data\sft\val.jsonl `
  --out-dir data\sft\instruction_aug `
  --sample-limit 20 `
  --batch-id sample
```

Review:

- `data/sft/instruction_aug/sample_aug.jsonl`
- `data/sft/instruction_aug/reports/sample_report.json`

After the sample quality is acceptable, run full split-preserving generation:

```powershell
python scripts\augment_sft_instructions.py `
  --mode full `
  --train data\sft\train.jsonl `
  --val data\sft\val.jsonl `
  --out-dir data\sft\instruction_aug `
  --batch-id full
```

Full generation writes `train_aug.jsonl`, `val_aug.jsonl`, and reports under
`data/sft/instruction_aug/reports/`. Train-derived records stay in train, and
validation-derived records stay in validation.
