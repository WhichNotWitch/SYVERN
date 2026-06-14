# SYVERN

SYVERN is the SysML V2 Evaluation and Reward Engine. This repository currently implements the H1 T0 core slice from the design docs: a deterministic validation and reward service with a stable `/validate` API, Stage 0-3 pipeline, unified JSON response, cache/fingerprint behavior, L1 rules, veto checks, and reward mapping.

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

The H1 adapter behavior is a deterministic harness, not a SysML parser. Markers such as `syntax_error`, `unresolved_ref`, `type_error`, and `parser_disagreement` exercise the stage gates for tests and local development.
