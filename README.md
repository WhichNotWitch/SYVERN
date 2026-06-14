# SYVERN

SYVERN is the SysML V2 Evaluation and Reward Engine. This repository currently implements the H1 T0 core plus the H2 deterministic robustness slice from the design docs: a validation and reward service with `/validate`, `/validate_batch`, Stage 0-3 pipeline, cross-parser element-summary agreement in `full` mode, batch `pass@k` / `stable@k` metrics, cache/fingerprint behavior, L1 rules, veto checks, and reward mapping.

## H1 Scope

Implemented:

- FastAPI service with `GET /health` and `POST /validate`
- Modes: `online_reward`, `full`, `data_filter`
- Stage 0 PARSE, Stage 1 RESOLVE, Stage 2 TYPECHECK, Stage 3 CONSTRAINT
- Deterministic Pilot and MontiCore stub adapters
- In-memory cache keyed by text hash, validator fingerprint, mode, and reference identity
- Anti-gaming veto and reward mapping
- Tests for API contract, gating, cache, veto, reward, and deterministic helpers

Not implemented in H1:

- Real SysML Pilot or MontiCore integration
- Stage 4 structural matching
- Stage 5 LLM intent judging
- IPT, persistence, dashboards, or production monitoring

## H2 Scope

Implemented:

- Normalized element summaries for parser adapter results
- `full` mode parser agreement using parse status plus element-summary multiset equality
- `POST /validate_batch` for deterministic batch robustness evaluation
- `pass_at_k` and `stable_at_k` aggregate metrics
- Stub markers `parser_disagreement` and `summary_disagreement` for exercising cross-parser veto behavior

Not implemented in H2:

- Real SysML Pilot or MontiCore integration
- Stage 4 structural matching
- IPT perturbation generation
- LLM or human intent judging
- Persistent storage, dashboards, or production monitoring

## Install

```powershell
python -m pip install -e ".[test]"
```

## Test

```powershell
python -m pytest -q
```

## Run

```powershell
python -m uvicorn syvern.api:app --reload
```

Then call:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part A attribute x","mode":"online_reward"}'
```

Batch robustness example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate_batch -ContentType "application/json" -Body '{"texts":["part A attribute x","part B unresolved_ref","part C type_error"],"mode":"online_reward"}'
```

The adapter behavior is a deterministic harness, not a SysML parser. Markers such as `syntax_error`, `unresolved_ref`, `type_error`, `parser_disagreement`, and `summary_disagreement` exercise the stage gates and H2 robustness checks for tests and local development.
