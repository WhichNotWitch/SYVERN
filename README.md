# SYVERN

SYVERN is the SysML V2 Evaluation and Reward Engine. This repository currently implements the H1 T0 core, H2 deterministic robustness slice, and H3 deterministic structural matching slice from the design docs: a validation and reward service with `/validate`, `/validate_batch`, Stage 0-4 pipeline, cross-parser element-summary agreement in `full` mode, batch `pass@k` / `stable@k` metrics, reference-based structural `precision` / `recall` / `f1` / `requirement_coverage`, cache/fingerprint behavior, L1 rules, veto checks, and reward mapping.

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

## H3 Scope

Implemented:

- Deterministic Stage 4 structural matching in `full` mode when `reference` is supplied
- Frozen exact matching policy `h3-frozen-exact-v1`
- Element-level `precision`, `recall`, `f1`, `requirement_coverage`, and `hallucinated_elements`
- Reference-aware cache behavior through the existing reference identity key
- T1 reward contribution through existing `w4` and `w5` terms after T0 passes

Not implemented in H3:

- Fuzzy matching, synonym dictionaries, or LLM semantic alignment
- GED calculation
- IPT perturbation
- Stage 5 intent judging
- Persistence, dashboards, or monitoring scatter plots

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

Structural matching example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full","reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},{"type":"attribute","qualified_name":"vehicle.mass"}],"requirements":["req.power","req.mass"],"coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}}}'
```

The adapter and structural behavior is a deterministic harness, not a real SysML parser. Markers such as `syntax_error`, `unresolved_ref`, `type_error`, `parser_disagreement`, and `summary_disagreement` exercise the stage gates and H2 robustness checks for tests and local development. H3 structural matching uses the same lightweight element markers as H2 and the exact frozen policy.
