# SYVERN Phase 2 Status

This file records which phase2 verification surfaces are real services and which are deterministic local harnesses. It is intentionally conservative: "wired" means the default application can select the backend through `SyvernSettings`; it does not claim semantic correctness for that backend.

| Surface | Default | Live wiring | Current evidence |
|---|---|---|---|
| L0 Pilot parse/resolve/typecheck | `PilotStubAdapter` | `PilotAdapter` via `pilot_endpoint` | HTTP adapter seam, fingerprint composition, JSONL alignment harness + CLI overall/stage/category gates |
| L0' MontiCore parser agreement | `MontiCoreStubAdapter` | `MontiCoreAdapter` via `monticore_endpoint` | HTTP adapter seam, full-mode agreement, JSONL alignment harness + CLI overall/stage/category gates |
| L1 rules/veto | local deterministic rules | local deterministic rules | unit tests and reward/veto regression tests |
| T1 structural matching | deterministic exact/normalized/fuzzy + GED accuracy | `LLMStructuralMatcherAdapter` via `structural_matcher_endpoint` | policy `h9-normalized-fuzzy-v1`, optional soft-match seam, structural regression tests |
| G4 IPT | caller-supplied perturbed outputs + rule perturbation generator | `LLMPerturbationAdapter` via `perturbation_endpoint` | original-output comparison, rule fallback, optional LLM perturbation seam tests |
| T2 intent judge | heuristic judge | `LLMIntentJudgeAdapter` via `intent_judge_endpoint` | source-labeled heuristic default, injectable HTTP seam |
| L2 formal analysis | disabled by default | `FormalAdapter` via `formal_endpoint` + `formal_tool` | response schema, timeout/error adapter seam, aggregate monitor rates |
| Cache | in-process LRU | `SQLiteValidationCache` selectable via `SyvernSettings.cache_path` | deep-copy isolation, LRU eviction, fingerprint isolation, SQLite roundtrip tests |
| Records/monitoring | in-process record store | `SQLiteValidationRecordStore` via `record_store_path` + optional `record_retention_limit` | endpoint divergence, formal aggregates, prompt-grouped stable@k, optional tenant-scoped summaries, SQLite roundtrip and retention tests |
| Dashboard data surface | `/dashboard_snapshot` JSON | same API auth + record store backends | aggregate summary, tenant rollups, bounded recent records without raw text/metadata |
| Configuration | dataclass defaults | `SYVERN_...` environment variables via `load_settings_from_env` | env parsing tests for endpoints, storage, auth, thresholds, and weights |
| API access | public by default | optional legacy/read/write/admin tokens + configurable `api_rbac_policy` + optional trusted-header identity group RBAC + local `/audit_events` stream + `SQLiteAuditEventStore` via `audit_log_path` + `HTTPAuditEventSink` via `audit_sink_endpoint` + optional `enforce_tenant_isolation` | protected endpoint tests, scope/policy enforcement tests, identity group RBAC tests, tenant recording tests, tenant-required validation/monitor/dashboard tests, auth audit tests, SQLite audit roundtrip and retention tests, best-effort HTTP audit export tests |
| Benchmarking | local helper + CLI gate | no hosted SLA target values yet | `benchmark_online_reward` latency/throughput helper; CLI can enforce `--max-average-latency-ms` and `--min-throughput-per-s` |
| CI | GitHub Actions | compileall + ruff + mypy + pytest + alignment smoke | workflow and tool config present; local CI gates verified |

## Alignment Datasets

`data/alignment/stub_smoke.jsonl` is a smoke fixture for the deterministic stubs. The `syvern align` CLI can enforce overall, parse, resolve, typecheck, minimum case count, and required category thresholds. The phase2 acceptance target remains a manually annotated SysML v2 dataset with at least 50 cases for real Pilot/MontiCore outputs, covering syntax errors, unresolved references, type errors, valid models, and nested/scale gradients.

## Still Open

- Point configured HTTP adapter seams at live SysML v2 services and run the alignment suite against real outputs.
- Add the full >= 50 case annotated SysML v2 alignment dataset.
- Set hosted SLA threshold values once live backend latency targets are known.
- Configure persistence paths and retention limits in deployment environments.
- Calibrate and run live LLM semantic-alignment matching against annotated outputs.
- Add a frontend dashboard and deploy behind a real IdP/reverse proxy for trusted identity headers.
