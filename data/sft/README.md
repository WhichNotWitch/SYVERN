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

Start Pilot on `8888` and SYVERN API on `8000`, then run:

```powershell
git clone --depth 1 https://github.com/Systems-Modeling/SysML-v2-Release.git data\sft\raw_sources\sysml-v2-release

python scripts\prepare_sft_data.py `
  --source-root data\sft\raw_sources\sysml-v2-release `
  --repo Systems-Modeling/SysML-v2-Release `
  --license EPL-2.0 `
  --seed data\sft\seed.jsonl `
  --out data\sft\interim\candidates.jsonl `
  --report data\sft\reports\prepare_report.json

python scripts\validate_and_filter.py `
  --in data\sft\interim\candidates.jsonl `
  --kept data\sft\interim\filtered.jsonl `
  --rejected data\sft\interim\rejected.jsonl `
  --report data\sft\reports\filter_report.json `
  --endpoint http://127.0.0.1:8000

python scripts\split_sft_data.py `
  --in data\sft\interim\filtered.jsonl `
  --train data\sft\train.jsonl `
  --val data\sft\val.jsonl `
  --report data\sft\reports\split_report.json
```

## Current Build

- Candidates: 308
- Passed data filter: 237
- Rejected: 71
- Pass rate: 76.95%
- Train: 213
- Val: 24
- Duplicate outputs after filtering: 0
- Train/val source-file overlap: 0

All final records pass the pinned validator fingerprint:

```text
syvern-phase2-pilot-http@0.8.0+rules@h4+intent@heuristic-h5+ops@h6+match@h9-normalized-fuzzy-v1+backends[pilot@pilot-0.59.0,monticore-stub@0.6.0]
```

Reports:

- `reports/prepare_report.json`: source commit and construct coverage before filtering.
- `reports/filter_report.json`: data-filter pass rate and rejection reasons.
- `reports/split_report.json`: dedupe, train/val sizes, and construct coverage.
- `reports/train_filter_report.json` and `reports/val_filter_report.json`: final pass checks.
