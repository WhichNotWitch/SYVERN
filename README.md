# SYVERN

**SYVERN** = *SysML V2 EValuation & Reward eNgine*

> **English** · [中文](README.zh.md)

> A gatekeeper for generated SysML v2: layered validation, evaluation **is** reward, and cheating doesn't pass.

SYVERN is a unified validation / evaluation / reward service for SysML v2 generation tasks. The
same checking logic produces a single JSON document that serves four use cases — SFT data
filtering, training evaluation & regression, RFT rejection sampling, and online RLVR reward — so
field definitions are frozen once in SFT and only weights are tuned in RL.

Design docs: [`doc/syvern_hld.md`](doc/syvern_hld.md) (high-level), [`doc/syvern_lld.md`](doc/syvern_lld.md)
(low-level), [`doc/sysmlv2_harness_final_design.md`](doc/sysmlv2_harness_final_design.md) (final spec),
and [`doc/syvern_phase2_design.md`](doc/syvern_phase2_design.md) (phase 2 productionization).

Usage manual: [`doc/USER_MANUAL.zh.md`](doc/USER_MANUAL.zh.md) covers installation, startup,
API calls, CLI workflows, environment variables, backend selection, security/RBAC, monitoring,
testing, and the local Pilot server.

> **Implementation status:** this repository now uses the local **Pilot HTTP service** as the
> primary L0 SysML v2 parser by default (`http://127.0.0.1:8888`). The validation/reward
> harness remains deterministic around that parser surface. HTTP adapter seams and configuration
> are available for MontiCore,
> Imandra/Gamma/nuXmv, an LLM judge, and an LLM structural matcher — see
> [Implementation status](#implementation-status).

---

## Core principles

1. **Evaluation = reward** — one validation path, one JSON; SFT freezes field semantics, RL tunes weights only.
2. **Convergence tiering** — only the deterministic core enters deterministic reward:
   - **T0** (parse / resolve / typecheck / metamodel rules) → deterministic reward signal
   - **T1** (structural F1 / coverage / GED) → down-weighted auxiliary reward (needs a frozen reference)
   - **T2** (intent fidelity, LLM-judge) → monitoring / preference only, **never** enters RLVR reward
3. **Stateless, cacheable, idempotent** — built for high-throughput online RL sampling.
4. **Version-pinned & reproducible** — backend versions are written into a fingerprint stamped on every result.
5. **Anti-gaming before recall** — the veto layer is a hard boundary that zeroes the reward.

---

## Architecture

```
                ┌──────────────────────────────────────────────┐
   model text → │  L0  Pilot Implementation (authoritative)     │ ← primary verdict   [local HTTP]
                │  L0' MontiCore parser (independent 2nd parser) │ ← cross-agreement   [stub/live optional]
                │  L1  metamodel-derived rules + anti-gaming     │ ← T0 + veto
                │  L2  formal tools (Imandra/Gamma/nuXmv)        │ ← deep, offline     [adapter seam]
                └──────────────────────────────────────────────┘
                                  ↓ unified JSON
```

### Validation pipeline (level-by-level gating)

| Stage | Check | Tier |
|---|---|---|
| **0 PARSE** | lexing/parsing succeeds? | T0 |
| **1 RESOLVE** | references resolve to declared elements? | T0 |
| **2 TYPECHECK** | type / KerML constraints? (non-blocking) | T0 |
| **3 CONSTRAINT** | metamodel rules + anti-gaming | T0 / veto |
| — *needs reference* — | | |
| **4 STRUCTURAL** | structural match against a reference model | T1 |
| **5 INTENT** | LLM-judge intent fidelity (offline/monitor) | T2 |

Any failed stage marks the rest `reached=false` ("not reached", distinct from `evaluated=false`
"not run"), which naturally produces stepwise reward shaping. Stages 0–3 need no reference and run on
any sample.

### Modules

| File | Responsibility |
|---|---|
| [`api.py`](src/syvern/api.py) | FastAPI gateway: routing, caching, record keeping |
| [`alignment.py`](src/syvern/alignment.py) | adapter alignment case loading and per-stage agreement scoring |
| [`benchmark.py`](src/syvern/benchmark.py) | local `online_reward` latency/throughput benchmark helper |
| [`cache.py`](src/syvern/cache.py) | validation response caches: in-memory default + SQLite persistence backend |
| [`cli.py`](src/syvern/cli.py) | command-line alignment smoke runner |
| [`pipeline_factory.py`](src/syvern/pipeline_factory.py) | settings-driven adapter selection + backend fingerprint composition |
| [`pipeline.py`](src/syvern/pipeline.py) | Stage 0–5 orchestration / gating state machine |
| [`storage_factory.py`](src/syvern/storage_factory.py) | settings-driven cache/record-store selection |
| [`adapters/`](src/syvern/adapters) | L0 Pilot/L0' MontiCore/L2 formal/LLM judge/LLM structural matcher HTTP adapter seams |
| [`rules.py`](src/syvern/rules.py) | L1 metamodel + anti-gaming rules with severity |
| [`veto.py`](src/syvern/veto.py) | Hard-boundary anti-gaming vetoes |
| [`structural.py`](src/syvern/structural.py) | T1 element matching, P/R/F1, requirement coverage, deterministic GED accuracy |
| [`ipt.py`](src/syvern/ipt.py) | Isomorphic Perturbation Testing consistency |
| [`intent.py`](src/syvern/intent.py) | T2 deterministic intent judge |
| [`calibration.py`](src/syvern/calibration.py) | Cohen's κ judge calibration helper |
| [`robustness.py`](src/syvern/robustness.py) | `pass@k` / `stable@k` aggregation |
| [`reward.py`](src/syvern/reward.py) | unified JSON → reward scalar (with veto gate) |
| [`monitoring.py`](src/syvern/monitoring.py) | aggregate summary + RL-divergence detection |
| [`records.py`](src/syvern/records.py) | validation event stores: in-memory default + SQLite persistence backend |
| [`settings.py`](src/syvern/settings.py) | weights, caps, thresholds, frozen fingerprints, env loading |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI gates: compile, ruff, mypy, pytest |

---

## Install

```powershell
python -m pip install -e ".[test]"
```

Requires Python ≥ 3.11.

## Test

```powershell
python -m pytest -q
```

## Local Pilot Server

SYVERN expects the real Pilot HTTP service on `http://127.0.0.1:8888` by default. The SysML v2
Jupyter kernel jar currently requires Java 21.

```powershell
Copy-Item .\scripts\pilot-real.local.example.ps1 .\scripts\pilot-real.local.ps1
# Edit scripts\pilot-real.local.ps1 and set $JAR, $LIB, and optionally $GRADLE_EXE.
powershell -ExecutionPolicy Bypass -File .\scripts\start-pilot-real.ps1
```

Then start the SYVERN API in another terminal:

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://127.0.0.1:8888"
python -m uvicorn syvern.api:app --reload
```

## Alignment Smoke

```powershell
syvern align --adapter pilot --dataset data/alignment/pilot_real_corpus.jsonl --min-overall 0.0 --min-parse 1.0
syvern align --adapter pilot --dataset data/alignment/pilot_real_corpus.jsonl --emit-calibrated data/alignment/pilot_real_calibrated.jsonl
```

## Online Reward Benchmark

Each non-empty line in the sample file is validated with `mode="online_reward"`.

```powershell
syvern benchmark --samples data/benchmark/samples.txt --max-average-latency-ms 250 --min-throughput-per-s 4
```

## Run

```powershell
python -m uvicorn syvern.api:app --reload
```

## Environment

The API loads `SyvernSettings` from `SYVERN_...` environment variables at startup. Examples:

```powershell
$env:SYVERN_PILOT_ENDPOINT="http://127.0.0.1:8888"
$env:SYVERN_MONTICORE_ENDPOINT="http://monticore.local/api"
$env:SYVERN_CACHE_PATH="data/syvern-cache.sqlite3"
$env:SYVERN_RECORD_STORE_PATH="data/syvern-records.sqlite3"
$env:SYVERN_RECORD_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_LOG_PATH="data/syvern-audit.sqlite3"
$env:SYVERN_AUDIT_RETENTION_LIMIT="10000"
$env:SYVERN_AUDIT_SINK_ENDPOINT="http://audit.local/events"
$env:SYVERN_AUDIT_SINK_TIMEOUT_S="2.0"
$env:SYVERN_API_TOKEN="secret-token"
$env:SYVERN_API_READ_TOKEN="read-token"
$env:SYVERN_API_WRITE_TOKEN="write-token"
$env:SYVERN_API_ADMIN_TOKEN="admin-token"
$env:SYVERN_API_RBAC_POLICY='{"read":["read"],"write":["write"],"admin":["read","write","admin"]}'
$env:SYVERN_ENABLE_IDENTITY_RBAC="true"
$env:SYVERN_IDENTITY_RBAC_POLICY='{"sysml-readers":["read"],"sysml-writers":["write"],"sysml-admins":["admin"]}'
$env:SYVERN_ENFORCE_TENANT_ISOLATION="true"
```

Reward weights can be overridden with `SYVERN_WEIGHT_W0` through `SYVERN_WEIGHT_W7`.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness check |
| `POST /validate` | validate one sample → unified JSON |
| `POST /validate_batch` | validate many → unified JSON list + `pass@k` / `stable@k` |
| `GET /reward_config` | current fingerprint, weights `w0..w7`, caps, `r_max`, policies |
| `GET /audit_events` | admin-only local auth decision audit stream without token values |
| `GET /monitor_summary` | aggregate window: pass/veto/formal rates, avg reward/coverage/latency |
| `GET /dashboard_snapshot` | dashboard-ready operational snapshot: summary, tenant rollups, recent records |

### Modes

- `online_reward` (default) — L0 + L1 only, high throughput. **Skips** L0' cross-check, structural, IPT, and intent.
- `full` — adds parser agreement, Stage 4 structural (needs `reference`), IPT (needs `perturbations` as perturbed model outputs), Stage 5 intent (needs `intent_reference`).
- `data_filter` — Stage 0–3 with gating thresholds.

### Examples

Online reward (single):

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"online_reward"}'
```

Batch robustness:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate_batch -ContentType "application/json" `
  -Body '{"texts":["part A.x","syntax_error","part C.y type_error"],"mode":"online_reward"}'
```

Full mode with reference (structural), perturbations as model outputs (IPT), and intent:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" `
  -Body '{"text":"part vehicle.engine attribute vehicle.mass","mode":"full",
  "reference":{"elements":[{"type":"part","qualified_name":"vehicle.engine"},
  {"type":"attribute","qualified_name":"vehicle.mass"}],
  "requirements":["req.power","req.mass"],
  "coverage":{"req.power":["vehicle.engine"],"req.mass":["vehicle.mass"]}},
  "perturbations":["attribute vehicle.mass part vehicle.engine"],
  "intent_reference":{"must_include":["vehicle.engine","vehicle.mass"],"must_not_include":["aircraft.wing"]}}'
```

Optional `metadata` (string→string) is recorded for monitoring but excluded from cache identity and responses.

### Unified output schema (abridged)

```jsonc
{
  "sample_id": "str",
  "tier_summary": { "t0_pass": bool, "t1_available": bool, "veto": bool },
  "stage": {
    "parse":      { "reached": bool, "ok": bool, "parser_agreement": bool|null, "errors": [] },
    "resolve":    { "reached": bool, "ok": bool, "unresolved_refs": int, "errors": [] },
    "typecheck":  { "reached": bool, "ok": bool, "type_errors": int, "errors": [] },
    "constraint": { "reached": bool, "ok": bool, "violations": [{ "rule": "...", "severity": "error|warn" }] }
  },
  "structural": { "evaluated": bool, "precision": 0.0, "recall": 0.0, "f1": 0.0,
                  "requirement_coverage": 0.0, "ged_accuracy": 0.0,
                  "hallucinated_elements": 0, "exact_matched": 0,
                  "normalized_matched": 0, "fuzzy_matched": 0, "soft_matched": 0,
                  "matching_policy_id": "h9-normalized-fuzzy-v1" },
  "robustness": { "stable_at_k": null, "ipt_consistent": null },
  "intent":     { "evaluated": bool, "score": null, "source": "heuristic|llm_judge|human|null" },
  "formal":     { "evaluated": bool, "tool": "imandra|gamma|nuxmv|null",
                  "status": "proved|failed|unknown|timeout|error|null",
                  "properties_checked": 0, "conclusions": [], "counterexamples": [] },
  "veto":       { "triggered": bool, "reason": "str|null" },
  "monitor":    { "codebleu": null, "levenshtein": null },
  "meta":       { "latency_ms": int, "mode": "str", "validator_fingerprint": "str",
                  "reward": 0.0, "text_hash": "str", "cache_hit": bool,
                  "data_filter_pass": bool|null,
                  "data_filter_reason": "passed|t0_failed|vetoed|reward_below_threshold|null" }
}
```

---

## Reward model

The veto gate fires before everything; T0 terms (`w0..w3`) form the stepladder backbone; T1 coverage
terms (`w4..w5`) are kept but down-weighted to deter empty models; `intent.score` is **never** used.

```python
if veto.triggered:
    r = 0.0                                          # hard boundary
else:
    r =  w0 * 1[parse_ok]                            # T0 stepladder
       + w1 * 1[resolve_ok]
       + w2 * (1 - norm(type_errors,  cap_type))
       + w3 * (1 - norm(violations_weighted, cap_cons))
       + w4 * f1_structural                          # T1, down-weighted
       + w5 * requirement_coverage                   # T1, anti empty-model
       + w6 * 1[ipt_consistent]                      # optional anti-gaming credit
       - w7 * norm(hallucinated_elements, cap_hall)
    r = clip(r, 0.0, r_max)
```

Defaults in [`settings.py`](src/syvern/settings.py): `w0=w1=0.25, w2=w3=0.20, w4=w5=0.05, w6=0.0, w7=0.10, r_max=1.0`.

### Anti-gaming vetoes ([`veto.py`](src/syvern/veto.py), [`rules.py`](src/syvern/rules.py))

`parser_disagreement` · `degenerate_output` (too few tokens/elements while passing) ·
filler text (`todo/tbd/???`) · excessive repetition · placeholder names (`foo`, `item1`, …) ·
enumeration-style gaming. Any hit ⇒ `reward = 0`.

---

## Determinism, caching & monitoring

- **Cache key** = `(text_hash, validator_fingerprint, mode, reference_id, perturbation_id, intent_reference_id, formal_properties_id)`.
  Same key ⇒ same result; a fingerprint change invalidates old entries.
- **Cache storage** is an in-process LRU store with deep-copy isolation and thread-level locking.
- **Record storage** defaults to memory, can use SQLite via `record_store_path`, and can cap retained
  validation events with `record_retention_limit`.
- **API access** is open by default; setting `api_token` keeps legacy all-scope access through
  `Authorization: Bearer ...` or `X-SYVERN-API-Key`. Optional `api_read_token`, `api_write_token`,
  and `api_admin_token` split protected endpoints into read (`/reward_config`, `/monitor_summary`,
  `/dashboard_snapshot`) and write (`/validate`, `/validate_batch`) scopes. `api_rbac_policy` can
  override the role-to-permission matrix; an `admin` permission grants all scopes.
  Auth decisions are recorded in an audit stream and can be read from `/audit_events` with admin
  scope; token values are never recorded. The audit stream defaults to memory, can use SQLite via
  `audit_log_path`, and can cap retained events with `audit_retention_limit`. `audit_sink_endpoint`
  enables best-effort HTTP export; sink failures do not block auth decisions or local audit storage.
  `enable_identity_rbac=true` enables trusted identity headers (`X-SYVERN-User`,
  `X-SYVERN-Groups`) from an upstream gateway/IdP and authorizes them with `identity_rbac_policy`;
  those identity subjects and groups are recorded in audit events.
  `X-SYVERN-Tenant` is recorded as event metadata. Setting `enforce_tenant_isolation=true` also
  requires `X-SYVERN-Tenant` for validation and monitoring/dashboard reads; monitor and dashboard
  aggregates are then scoped to that tenant.
- **Online reward path is pure-deterministic** — non-deterministic work (soft semantic alignment, LLM
  judge) is disabled outside `full` mode.
- **RL valid-region monitoring** — `detect_divergence` flags `semantic_without_coverage`,
  `veto_rate_increase`, and `stable_at_k_drop` between two aggregate windows (the "passing but empty /
  gaming" reward-hacking signal).

---

## Implementation status

The pipeline, schema, reward map, anti-gaming, and monitoring surfaces are fully implemented and
verified by **306 passing tests**. Milestones H1–H6 are delivered against the design baseline, with
phase-2 slices for online parser-agreement semantics, prompt-grouped stable@k, and deterministic
normalized/fuzzy structural matching plus deterministic GED accuracy, original-output-based IPT consistency, and honest heuristic
intent source labeling, LRU/thread-locked caching with an optional SQLite backend, and explicit data-filter pass/drop
decisions, deterministic rule-based IPT spec perturbation generation with an optional LLM perturbation seam, and fingerprintable Pilot and
MontiCore HTTP adapter seams, settings/env-driven backend wiring, timeout-safe L2 formal response and aggregate monitoring, optional record
retention limits, optional API token
protection with tenant event metadata, optional trusted-header identity RBAC, optional SQLite auth audit events, and optional HTTP audit export, plus
injectable LLM intent judge and structural soft-match seams. The API now builds its pipeline through settings-driven backend
wiring, so configured live adapters contribute their fingerprints to every result and cache key.
Validation events, audit events, and cache payloads can also be stored in SQLite-backed stores by
setting `record_store_path`, `audit_log_path`, and `cache_path`; event retention can be capped with
`record_retention_limit` and `audit_retention_limit`. Auth audit events can also be exported to an
external HTTP sink with `audit_sink_endpoint`.
Phase2 status is tracked in [`STATUS.md`](STATUS.md). Real-Pilot alignment inputs live under
[`data/alignment/pilot_real_corpus.jsonl`](data/alignment/pilot_real_corpus.jsonl).

| Milestone | Delivered | Notes |
|---|---|---|
| H1 — T0 core | Stage 0–3, reward, cache, fingerprint, Pilot HTTP adapter seam | local Pilot HTTP service on port 8888 by default |
| H2 — cross & robust | L0' agreement, `pass@k` / `stable@k`, `/validate_batch`, MontiCore HTTP adapter seam | stub MontiCore by default; live MontiCore via settings |
| H3/H9 — structural | Stage 4, frozen policy `h9-normalized-fuzzy-v1`, P/R/F1, coverage, deterministic GED accuracy, hallucination, exact/normalized/fuzzy/soft match counts | soft matching is optional via HTTP seam |
| H4/H10 — anti-gaming/IPT | veto layer + caller-supplied IPT comparing perturbed outputs to the original output + rule-based spec perturbation generator + optional LLM perturbation seam | LLM perturbation is offline/helper-only |
| H5/H11 — intent & calibration | deterministic Stage 5 heuristic, injectable LLM judge adapter seam, Cohen's κ helpers, honest source labeling | heuristic by default; live judge via settings |
| H6/H12 — reward-ready | `/reward_config`, `/audit_events`, `/monitor_summary`, `/dashboard_snapshot`, endpoint divergence alerts, throughput smoke test, in-process LRU cache, env/settings-selectable SQLite cache/record/audit stores, record/audit retention caps, optional best-effort HTTP audit export, data-filter gate, optional legacy/read/write/admin API tokens with configurable RBAC policy, optional trusted-header identity group RBAC, tenant event metadata, local auth audit events, optional tenant-isolated monitor/dashboard reads, L2 formal adapter seam, response reporting, formal aggregate rates, backend factory wiring, alignment harness, benchmark helper, CLI alignment stage/category gates, and CLI latency/throughput gates | API default remains in-memory/open; hosted SLA targets still need deployment-specific values |
| G8 — CI | GitHub Actions workflow for compileall, ruff, mypy, and pytest | real Pilot alignment is run against the operator's Pilot service |

**Known simplifications (by design, not defects):**

- The primary L0 parser is the configured Pilot HTTP service, defaulting to
  `http://127.0.0.1:8888`. The in-repo deterministic adapters remain available only as internal
  test utilities; the public API and CLI no longer expose stub/subset L0 selection.
  Set `monticore_endpoint`, `formal_endpoint`, `intent_judge_endpoint`,
  `structural_matcher_endpoint`, or `perturbation_endpoint` in `SyvernSettings` to use the
  corresponding auxiliary HTTP adapter.
- `/monitor_summary` compares the current aggregate window with the previous endpoint call; the
  baseline is in process memory and resets with the service.
- Aggregate `stable_at_k` is grouped by `metadata.prompt_id` when provided; ungrouped events are
  treated as one-sample prompt groups.
- Not implemented: the full >= 50 case real-backend alignment dataset, calibrated live semantic-alignment
  matching, frontend dashboards, and deployment behind a real IdP/reverse proxy for trusted identity headers.

**Next steps:** calibrate the real-Pilot alignment corpus against the local Pilot service, decide the
production Pilot endpoint/deployment shape beyond `127.0.0.1:8888`, configure `cache_path` /
`record_store_path` / retention in deployments, and set hosted SLA thresholds once backend latency
targets are known.
