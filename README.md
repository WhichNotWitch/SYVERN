# SYVERN

SYVERN is the SysML V2 Evaluation and Reward Engine. This repository currently implements the H1 T0 core, H2 deterministic robustness slice, H3 deterministic structural matching slice, H4 deterministic anti-gaming/IPT slice, H5 deterministic intent-judging/calibration harness, and H6 deterministic reward-readiness/monitoring harness from the design docs: a validation and reward service with `/validate`, `/validate_batch`, `/reward_config`, `/monitor_summary`, Stage 0-5 pipeline, cross-parser element-summary agreement in `full` mode, batch `pass@k` / `stable@k` metrics, reference-based structural `precision` / `recall` / `f1` / `requirement_coverage`, anti-gaming vetoes, caller-supplied IPT consistency, deterministic intent judging, Cohen's kappa calibration helpers, cache/fingerprint behavior, in-memory validation event recording, monitor summaries, reward configuration visibility, L1 rules, veto checks, and reward mapping.

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
- Stage 4 structural matching, which was deferred to H3 scope
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
- Stage 4 structural matching, which was deferred to H3 scope
- IPT perturbation generation
- LLM or human intent judging
- Persistent storage, dashboards, or production monitoring

## H3 Scope

Implemented:

- Deterministic Stage 4 structural matching in `full` mode when `reference` is supplied and T0 passes without veto
- Frozen exact matching policy `h3-frozen-exact-v1`
- Element-level `precision`, `recall`, `f1`, and `hallucinated_elements`, plus requirement-level `requirement_coverage`
- Reference-aware cache behavior through the existing reference identity key
- T1 reward contribution through existing `w4` and `w5` terms after T0 passes

Not implemented in H3:

- Fuzzy matching, synonym dictionaries, or LLM semantic alignment
- GED calculation
- IPT perturbation
- Stage 5 intent judging
- Persistence, dashboards, or monitoring scatter plots

## H4 Scope

Implemented:

- Deterministic hard vetoes for parser disagreement and degenerate output, plus anti-gaming vetoes for filler placeholders, excessive repetition, placeholder element names, and enumeration-style generated structures
- Deterministic IPT consistency in `full` mode when `reference` and caller-supplied `perturbations` are present and T0 passes without veto
- Perturbation-aware cache behavior through a frozen perturbation identity
- Reward `w6` compatibility for callers that enable IPT positive credit

Not implemented in H4:

- LLM-generated perturbations
- Human equivalence verification
- Real SysML semantic equivalence checking
- Stage 5 intent judging
- Persistence, dashboards, or production monitoring scatter plots

## H5 Scope

Implemented:

- Deterministic Stage 5 intent-judging harness in `full` mode when `intent_reference` is supplied and T0 passes without veto
- Optional `intent_reference` request field, separate from the structural `reference`
- Fixed local rubric for coverage, correctness, and overfit/underfit scoring
- `intent.score` population with `source="llm_judge"` for schema compatibility
- Cohen's kappa calibration helpers for human/judge agreement checks
- Intent-reference-aware cache behavior
- Tests proving `intent.score` does not affect deterministic reward

Not implemented in H5:

- Real external LLM judge calls
- Agentic multi-step judging
- Pairwise preference endpoints
- Human review UI or persistent calibration storage
- Cross-model judge ensembles
- Automatic rubric rewriting when kappa is low
- Running Stage 5 in `online_reward` or `data_filter`

## H6 Scope

Implemented:

- In-memory validation event recording for `/validate` and `/validate_batch`
- Optional string metadata on validation requests, recorded for monitoring but excluded from cache identity and validation responses
- `GET /reward_config` for the current validator fingerprint, reward weights `w0..w7`, caps, `r_max`, matching policy, judge model, rubric version, and IPT threshold
- `GET /monitor_summary` for aggregate record count, semantic pass rate, T0 pass rate, T1 availability, veto rate, average requirement coverage, average reward, average latency, stable rate, and the single-window divergence alert field
- Deterministic divergence helpers for `semantic_without_coverage`, `veto_rate_increase`, and `stable_at_k_drop`
- A local `online_reward` throughput smoke test that sends reference, perturbation, and intent inputs while checking full-mode-only structural, IPT, and intent work does not leak into the online path

Not implemented in H6:

- Persistent storage for validation records
- Dashboard UI, charts, or frontend visualization
- External metrics systems, hosted logging, or tracing
- Authentication, tenancy, retention policies, or background jobs
- Real SysML backend performance benchmarking
- Runtime mutation of reward weights or verifier configuration

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

Reward operations examples:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/reward_config
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/monitor_summary
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part A attribute x","mode":"online_reward","metadata":{"domain":"vehicle","checkpoint":"rft-001"}}'
```

Structural matching example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full","reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},{"type":"attribute","qualified_name":"vehicle.mass"}],"requirements":["req.power","req.mass"],"coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}}}'
```

IPT example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full","reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},{"type":"attribute","qualified_name":"vehicle.mass"}],"requirements":["req.power","req.mass"],"coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}},"perturbations":["attribute vehicle.mass part vehicle.engine"]}'
```

Intent judging example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full","intent_reference":{"requirements":["model engine","include mass"],"must_include":["vehicle.engine","vehicle.mass"],"must_not_include":["aircraft.wing"]}}'
```

The H5 intent judge is a deterministic local harness, not a real LLM call. It preserves the Stage 5 schema and calibration boundary so future LLM judge adapters can be added without changing the deterministic reward path. `intent.score` is for monitoring and preference workflows only; it is not used by `reward.py`.

The H6 monitor is also local and deterministic. Validation records are held in process memory and reset when the service restarts. Cache hits are still recorded as validation service events, so `/monitor_summary` reflects API traffic rather than only fresh pipeline executions. The `/monitor_summary` endpoint returns a single-window summary whose `divergence_alerts` field is empty; cross-window divergence detection is available as a pure helper for callers that compare previous and current aggregate windows. The online reward smoke test is a local regression check, not a real SysML backend benchmark.

The adapter, structural, and IPT behaviors are a deterministic harness, not a real SysML parser or equivalence prover. Markers such as `syntax_error`, `unresolved_ref`, `type_error`, `parser_disagreement`, and `summary_disagreement` exercise the stage gates and H2 robustness checks for tests and local development. H3 structural matching and H4 IPT use the same lightweight element markers and exact frozen policy.
