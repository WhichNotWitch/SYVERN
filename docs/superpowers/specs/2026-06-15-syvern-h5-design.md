# SYVERN H5 Intent Judging And Calibration Design

## Purpose

H5 adds the Stage 5 intent-judging and calibration layer described in the SYVERN design documents. H1-H4 made the deterministic T0 core, parser robustness, structural matching, anti-gaming vetoes, and IPT consistency executable. H5 makes the T2 boundary executable without weakening the core reward contract: intent scores are monitoring and preference signals only, never deterministic RLVR reward inputs.

The milestone uses a deterministic local judge harness instead of a real external LLM call. This keeps the repository testable without network access, API keys, or non-reproducible model outputs while preserving the production interface shape for a future LLM judge adapter.

## Scope

Included in H5:

- A focused intent-judging module with a fixed rubric and deterministic local scoring harness.
- Optional request input for `intent_reference`, separate from the H3/H4 structural `reference`.
- Stage 5 intent evaluation in `full` mode only when T0 passes, veto is clear, and `intent_reference` is supplied.
- `intent.score` population on eligible full-mode requests, with `source="llm_judge"` for schema compatibility.
- Judge configuration fields in settings, including `judge_model`, `rubric_version`, `intent_vote_count`, and `kappa_min`.
- A calibration module that computes Cohen's kappa between human labels and judge labels.
- Cache behavior that distinguishes intent-reference identity.
- Tests proving intent stays out of reward, online reward stays deterministic, and calibration works.
- README updates describing H5 behavior and deterministic limits.

Excluded from H5:

- Real LLM API calls.
- Agentic multi-step judge workflows.
- Pairwise preference ranking endpoints.
- Human review UI or persistent calibration storage.
- Cross-model judge ensembles.
- Automatic rubric rewriting when kappa is low.
- Using `intent.score` in RLVR reward.
- Running Stage 5 in `online_reward` or `data_filter` mode.

## Architecture

H5 adds two focused modules and extends the validation request path:

- `intent.py`: evaluates generated text against a caller-supplied intent reference using a fixed deterministic rubric harness.
- `calibration.py`: computes Cohen's kappa and reports whether judge/human agreement meets the configured threshold.
- `models.py`: adds `intent_reference` request fields and response models for calibration helpers if needed.
- `settings.py`: adds judge and calibration configuration and updates the validator fingerprint.
- `normalization.py`: adds intent-reference identity for cache keys.
- `cache.py`: extends cache keys with intent-reference identity.
- `pipeline.py`: evaluates intent only for eligible `full` requests after deterministic gates.
- `api.py`: forwards `intent_reference` and includes it in the cache key.
- `README.md`: documents H5 scope and a full-mode intent example.

The design keeps intent judging separate from structural matching. `reference` remains the H3/H4 structural target. `intent_reference` describes what the generated model is supposed to express at the natural-language or rubric level.

## Request Shape

H5 extends validation requests with an optional `intent_reference` field:

```json
{
  "text": "part vehicle.engine attribute vehicle.mass",
  "mode": "full",
  "reference": {
    "elements": [
      {"type": "part", "qualified_name": "vehicle.engine"},
      {"type": "attribute", "qualified_name": "vehicle.mass"}
    ],
    "requirements": ["req.power", "req.mass"],
    "coverage": {
      "req.power": ["vehicle.engine"],
      "req.mass": ["vehicle.mass"]
    }
  },
  "intent_reference": {
    "requirements": [
      "model the vehicle engine",
      "include vehicle mass as an attribute"
    ],
    "must_include": ["vehicle.engine", "vehicle.mass"],
    "must_not_include": ["aircraft.wing"]
  }
}
```

Rules:

- `intent_reference` is optional.
- Missing or empty `intent_reference` keeps `intent.evaluated=false`, `intent.score=null`, and `intent.source=null`.
- `intent_reference.requirements` is a list of intent statements.
- `intent_reference.must_include` is a list of normalized phrases that should appear in the generated text.
- `intent_reference.must_not_include` is a list of normalized phrases that should not appear in the generated text.
- Unknown keys in `intent_reference` are ignored by the deterministic H5 harness so callers can carry richer future judge metadata.

## Intent Eligibility

Stage 5 runs only when all of the following are true:

- Request mode is `full`.
- A non-null `intent_reference` is supplied.
- Parse, resolve, and typecheck pass for the original text.
- Constraint stage is reached and passes for the original text.
- Veto has not triggered for the original text.

Stage 5 does not require Stage 4 structural matching to be evaluated. A caller may judge intent without a structural reference. When both `reference` and `intent_reference` are supplied, Stage 4 and Stage 5 can both evaluate in the same full-mode response.

When Stage 5 is not eligible, `intent` remains the documented default:

```json
{"evaluated": false, "score": null, "source": null}
```

## Rubric Harness

The production design calls for a single model, fixed rubric, and multiple votes. H5 implements the same shape with deterministic local logic.

Rubric dimensions:

- `coverage`: how many required intent statements and `must_include` phrases are represented.
- `correctness`: whether forbidden or contradictory phrases are absent.
- `overfit_underfit`: whether the generated text is neither empty/minimal nor dominated by unrelated content.

Each dimension maps to a 0-5 score. The final `intent.score` is the arithmetic mean of deterministic votes, clipped to `[0.0, 5.0]`.

Default scoring policy:

- Coverage score is `5 * matched_required / total_required` when required items exist; otherwise `null` for the dimension.
- Correctness score is `5.0` when no forbidden item appears, otherwise `max(0.0, 5.0 - 2.5 * forbidden_matches)`.
- Overfit/underfit score starts at `5.0`, subtracts for too few model tokens, and subtracts for high unrelated-token ratio against supplied reference phrases.
- The final score averages only dimensions with enough input to evaluate.
- If no dimension has enough input, intent remains unevaluated.

This is a deterministic harness, not a claim of semantic understanding. It exists to lock API behavior, gating, cache semantics, calibration utilities, and reward isolation before a real LLM judge adapter is available.

## Voting And Bias Controls

H5 records the production bias-control decisions in executable form where possible:

- The harness hides generator identity because no generator identity is accepted in the request.
- Pointwise scoring is the only H5 mode. Pairwise order swapping is not implemented because H5 does not add pairwise comparison endpoints.
- `settings.intent_vote_count` controls the number of deterministic votes. Votes use the same rubric and return the same score, making repeated local tests reproducible.
- `settings.judge_model` defaults to a stub identifier such as `h5-deterministic-judge`.
- `settings.rubric_version` identifies the frozen rubric and is included in the validator fingerprint.

Future real judge adapters can preserve this interface while replacing deterministic votes with actual model calls, median aggregation, order swapping for pairwise comparisons, and cross-model ensembles.

## Calibration

H5 adds Cohen's kappa utilities for ongoing judge calibration.

Input labels:

- Human labels are integer buckets from 0 to 5.
- Judge labels are integer buckets from 0 to 5.
- Lists must be the same non-zero length.

Behavior:

- `cohen_kappa(human_labels, judge_labels)` returns a float in `[-1.0, 1.0]`.
- Exact agreement produces `1.0`.
- Agreement equal to chance produces `0.0`.
- Worse-than-chance agreement can be negative.
- Degenerate all-one-class cases return `1.0` if both sequences are identical, otherwise `0.0`.
- `calibration_passed` is true when `kappa >= settings.kappa_min`.

Calibration is a production control loop signal. H5 reports whether agreement meets threshold; it does not rewrite the rubric automatically and does not change reward behavior.

## Reward Behavior

H5 does not change the reward formula.

Required invariants:

- `reward.py` must not read `response.intent.score`.
- Changing `intent.score` from `0.0` to `5.0` must not change computed reward.
- Veto still forces reward `0.0`.
- `online_reward` remains a deterministic T0 path and does not run Stage 5.
- `data_filter` does not run Stage 5.

This preserves the HLD/LLD boundary that T2 intent is only for monitoring dashboards and RLHF/DPO preference data.

## Cache And Determinism

The validation cache key must include intent-reference identity so that the same text/mode/reference with different intent criteria cannot reuse stale Stage 5 results.

Intent-reference identity is deterministic:

- Missing and empty intent references share the "no intent" identity.
- Non-empty intent references are serialized with sorted keys and normalized whitespace for string values.
- List order is preserved, because future rubric versions may expose per-item details.
- The validator fingerprint includes judge and rubric configuration.

Repeated calls with identical text, mode, structural reference identity, perturbation identity, intent-reference identity, and validator fingerprint must return the same response except for `meta.cache_hit`.

## Error Handling

- Missing `intent_reference`: intent remains unevaluated.
- Empty `intent_reference`: intent remains unevaluated.
- Blank required phrase: ignored for scoring.
- Non-string list entries: ignored by the harness after Pydantic accepts the JSON object.
- No evaluable rubric dimensions: intent remains unevaluated.
- Original request T0 failure: intent remains unevaluated.
- Original request veto: intent remains unevaluated.
- Calibration lists with different lengths or zero length: raise `ValueError`.
- Calibration labels outside 0-5: raise `ValueError`.

## Testing

Required H5 coverage:

- `full` mode with `intent_reference` and matching generated text sets `intent.evaluated=true`, a positive `intent.score`, and `source="llm_judge"`.
- `full` mode with forbidden content lowers the intent score.
- Missing `intent_reference` leaves intent unevaluated.
- `online_reward` and `data_filter` do not run intent judging even when `intent_reference` is supplied.
- T0 failure or veto prevents intent judging.
- Intent judging can run without structural `reference`.
- Reward is unchanged by low versus high intent scores.
- API cache distinguishes different intent references.
- Cohen's kappa returns `1.0` for exact agreement.
- Cohen's kappa returns a value below `settings.kappa_min` for clearly poor agreement.
- Calibration rejects empty, mismatched, or out-of-range label inputs.
- Existing H1-H4 tests continue to pass.

## Delivery Criteria

H5 is accepted when:

- `pytest` passes.
- `/validate` in `full` mode with `intent_reference` returns an evaluated intent summary.
- `/validate` in `online_reward` mode keeps intent unevaluated.
- Reward remains identical for otherwise equivalent responses with different intent scores.
- Calibration reports kappa and pass/fail status against `settings.kappa_min`.
- README documents H5 scope, deterministic judge limits, and reward isolation.

## Later Milestones

H6 adds persistence, monitoring, reward operations, and the `semantic_pass` by `requirement_coverage` divergence checks described in the design documents. A later production hardening pass can replace the H5 deterministic judge harness with real LLM judge adapters, human review storage, pairwise preference collection, and continuous rubric revision workflows.
