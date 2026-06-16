# SYVERN H6 Reward Readiness And Monitoring Design

## Purpose

H6 makes SYVERN operationally ready as the local reward and monitoring harness described in the design documents. H1-H5 made the validation stages, structural matching, anti-gaming/IPT, and intent calibration executable. H6 closes the loop around reward operations: recorded validation results, reward configuration visibility, online-reward smoke throughput, and RL effective-range monitoring for `semantic_pass` by `requirement_coverage` divergence.

This milestone stays intentionally local and deterministic. It does not introduce a production database, dashboard UI, message bus, or external observability stack. Instead, it adds small in-memory and pure-computation components that make the production boundaries executable and testable.

## Scope

Included in H6:

- In-memory result recording for API validation calls.
- Optional request metadata for monitoring dimensions such as `domain`, `difficulty`, and `checkpoint`.
- Aggregate monitoring summaries over recorded validation results.
- Deterministic RL effective-range divergence detection using `semantic_pass`, `requirement_coverage`, `veto_rate`, `stable_at_k`, and reward aggregates.
- Reward configuration visibility and validation helpers for `w0..w7`, caps, `r_max`, and the current validator fingerprint.
- API endpoints for reward configuration and monitor summary.
- Conservative online-reward throughput smoke coverage for the local stub path.
- README updates documenting H6 behavior and local-only limits.

Excluded from H6:

- Real persistent storage such as SQLite, Postgres, object storage, or event streams.
- Dashboard UI, charts, or frontend visualization.
- External metrics systems such as Prometheus, OpenTelemetry, or hosted logging.
- Authentication, tenancy, retention policies, or background jobs.
- Real SysML backend performance benchmarking.
- Changing the deterministic reward formula except to expose and validate its configuration.
- Adding CodeBLEU or Levenshtein scoring to reward.

## Architecture

H6 adds three focused modules and extends the API boundary:

- `records.py`: in-memory validation result store and compact `ValidationRecord` representation.
- `monitoring.py`: aggregate monitor summaries and divergence detection helpers.
- `reward_ops.py`: reward configuration summary and settings validation helpers.
- `models.py`: request metadata and monitor/reward operation response models.
- `api.py`: records API validation results and exposes local operations endpoints.
- `settings.py`: monitoring thresholds and H6 validator fingerprint.
- `README.md`: documents H6 scope, endpoints, and local-only limits.

The API remains a single-process local harness. The in-memory result store is intentionally reset when the process restarts and is directly clearable in tests through the module-level store object.

## Request Metadata

H6 extends validation request models with optional metadata:

```json
{
  "text": "part vehicle.engine attribute vehicle.mass",
  "mode": "full",
  "metadata": {
    "domain": "vehicle",
    "difficulty": "easy",
    "checkpoint": "rft-001"
  }
}
```

Rules:

- `metadata` is optional.
- Metadata values are strings.
- Metadata does not affect validation, reward, or cache identity.
- Metadata is copied into validation records so monitor summaries can later be grouped or filtered.
- H6 does not add query filters by metadata; it only preserves the metadata in records.

## Result Recording

H6 records API validation responses after validation and cache lookup have completed.

Record fields:

- `sample_id`
- `text_hash`
- `mode`
- `validator_fingerprint`
- `cache_hit`
- `semantic_pass`
- `t0_pass`
- `t1_available`
- `veto_triggered`
- `veto_reason`
- `requirement_coverage`
- `stable_at_k`
- `reward`
- `latency_ms`
- `metadata`

Recording behavior:

- `/validate` records one response per request.
- `/validate_batch` records every item response in order.
- Cache hits are recorded because they are still validation service events.
- Recording does not mutate the response payload.
- Recording is in-memory only.

## Monitor Summary

H6 exposes a monitor summary over recorded events.

Summary fields:

- `record_count`
- `semantic_pass_rate`
- `t0_pass_rate`
- `t1_available_rate`
- `veto_rate`
- `average_requirement_coverage`
- `average_reward`
- `average_latency_ms`
- `stable_at_k`
- `divergence_alerts`

Definitions:

- `semantic_pass` uses the existing `robustness.semantic_pass(response)` helper.
- `average_requirement_coverage` treats unevaluated structural summaries as `0.0`.
- `stable_at_k` is the share of recorded responses whose semantic path passed.
- `divergence_alerts` is empty for a single aggregate window unless a caller uses the pure divergence helper with a previous window.

The summary is monitoring output only and never feeds back into `compute_reward`.

## Divergence Detection

The RL effective-range monitor compares two aggregate windows.

Inputs:

- Previous `MonitorAggregate`.
- Current `MonitorAggregate`.
- H6 monitoring thresholds from settings.

Alert rules:

- `semantic_without_coverage`: current semantic pass rate rises by at least `monitor_semantic_gain_threshold`, while current average requirement coverage rises by no more than `monitor_coverage_stall_threshold`.
- `veto_rate_increase`: current veto rate rises by at least `monitor_veto_rate_increase_threshold`.
- `stable_at_k_drop`: current stable rate falls by at least `monitor_stable_drop_threshold`.

Each alert has:

- `code`
- `message`
- `severity`, either `warn` or `error`

Default H6 severities:

- `semantic_without_coverage`: `warn`
- `veto_rate_increase`: `warn`
- `stable_at_k_drop`: `warn`

H6 does not stop requests or change rewards when alerts fire. Alerts are operator signals that the verifier reward may be leaving its effective range.

## Reward Operations

H6 makes reward configuration visible and checkable.

Reward config summary fields:

- `validator_fingerprint`
- `weights` with all `w0..w7`
- `caps` for `cap_type`, `cap_cons`, and `cap_hall`
- `r_max`
- `matching_policy_id`
- `judge_model`
- `rubric_version`
- `ipt_threshold`

Settings validation checks:

- All weights are present.
- Caps are positive.
- `r_max` is positive.
- `validator_fingerprint` is non-empty.
- `matching_policy_id` is non-empty.

Reward operations are observational in H6. They do not change weights at runtime and do not introduce a mutable admin endpoint.

## API Endpoints

H6 adds two read-only endpoints:

- `GET /reward_config`
- `GET /monitor_summary`

`GET /reward_config` returns the reward config summary.

`GET /monitor_summary` returns the aggregate monitor summary for the current in-memory result store.

Existing endpoints keep their response shapes:

- `GET /health`
- `POST /validate`
- `POST /validate_batch`

The `POST` endpoints accept optional `metadata`, but metadata is not echoed in the existing validation response schema.

## Throughput Smoke

H6 adds a conservative local throughput smoke test for `online_reward`.

The test validates a small fixed set of deterministic stub samples through `ValidationPipeline.validate(..., mode="online_reward")` and asserts that local execution completes under a generous threshold. The threshold must be loose enough to avoid CI flakiness and should only catch accidental large slowdowns such as expensive full-mode work leaking into the online path.

This is not a real SysML backend benchmark and must be documented as a local stub smoke check.

## Cache And Determinism

H6 does not change validation cache identity except for the H6 validator fingerprint.

Important cache rules:

- Request metadata does not enter the validation cache key.
- Two requests with the same text, mode, references, perturbations, intent reference, and fingerprint may share the cached response even if metadata differs.
- Both service events still produce distinct records with their own metadata and cache-hit flag.
- Monitor summaries are deterministic for a fixed sequence of recorded responses.

## Error Handling

- Missing metadata: record metadata is `{}`.
- Non-string metadata values: Pydantic rejects the request.
- Empty result store: monitor summary returns zero rates and empty alerts.
- Reward settings validation failure: `/reward_config` should surface an internal error in real service operation; unit tests should cover the helper directly.
- Divergence detection with empty previous or current windows returns no semantic/coverage trend alert unless a veto or stable-rate threshold can be computed from the provided aggregates.

## Testing

Required H6 coverage:

- Request metadata is accepted by validate and batch request models.
- Metadata does not change cache identity.
- `/validate` records one validation event.
- `/validate_batch` records every item response in order.
- Cache hits are recorded as service events.
- Monitor summary computes record count, semantic pass rate, T0 pass rate, T1 availability, veto rate, average coverage, average reward, average latency, and stable rate.
- Empty monitor summary returns zero rates and no alerts.
- Divergence helper emits `semantic_without_coverage` when semantic pass rises but coverage stalls.
- Divergence helper emits `veto_rate_increase` when veto rate rises beyond threshold.
- Divergence helper emits `stable_at_k_drop` when stable rate drops beyond threshold.
- Reward config summary exposes all weights and caps.
- Reward settings validation rejects invalid caps or missing identifiers.
- `online_reward` throughput smoke stays within the conservative local threshold.
- Existing H1-H5 tests continue to pass.

## Delivery Criteria

H6 is accepted when:

- `pytest` passes.
- `GET /reward_config` returns all reward weights, caps, and fingerprint details.
- `GET /monitor_summary` returns zero summary on a fresh store and non-zero aggregates after validation calls.
- API validation calls record monitor events without changing validation responses.
- Divergence detection can flag the documented `semantic_pass` by `requirement_coverage` failure mode.
- `online_reward` remains fast in the local smoke test and does not run full-mode-only H4/H5 work.
- README documents H6 local monitoring, reward operations, and non-production storage limits.

## Final Project Boundary

After H6, this repository implements the full H1-H6 local deterministic SYVERN harness described in the docs. It remains a stubbed local harness, not a production SysML backend service. Production work after H6 can replace stubs with real Pilot/MontiCore/L2 integrations, persistent storage, dashboards, authentication, deployment packaging, and external monitoring while preserving the response and reward boundaries established here.
