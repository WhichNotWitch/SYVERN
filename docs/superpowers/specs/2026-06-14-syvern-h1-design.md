# SYVERN H1 T0 Core Design

## Purpose

Build the first executable slice of SYVERN from the documents in `doc/`: a deterministic validation and reward service for the H1 milestone. H1 covers the T0 core: service API, Stage 0-3 pipeline, unified JSON response, validator fingerprinting, idempotent caching, L1 rules, anti-gaming veto checks, reward mapping, and tests.

This slice must make the requested end state more true without pretending that the full H1-H6 system is complete. It creates stable interfaces for later integration with real SysML v2 backends, structure matching, IPT, intent judging, storage, and monitoring.

## Scope

Included in H1:

- A Python service project using FastAPI, Pydantic, and pytest.
- `POST /validate` with request shape `{text, reference?, mode, k?}` and modes `online_reward`, `full`, and `data_filter`.
- Unified response schema matching the LLD fields: `sample_id`, `tier_summary`, `stage`, `structural`, `robustness`, `intent`, `veto`, `monitor`, and `meta`.
- Stage 0 PARSE, Stage 1 RESOLVE, Stage 2 TYPECHECK, and Stage 3 CONSTRAINT orchestration.
- Clear distinction between `reached=false` for stages blocked by gating and `evaluated=false` for stages skipped by mode or missing reference.
- Adapter interfaces for Pilot and MontiCore style validation, with deterministic local stub implementations for H1.
- L1 rule engine with rule IDs, severity, category, and weighted violation calculation.
- Anti-gaming veto checks for degenerate output, filler output, anti-gaming rule hits, and parser disagreement when available.
- Reward mapping from unified JSON and config weights, with veto forcing reward `0.0` and `intent.score` excluded from the reward formula.
- In-memory cache keyed by normalized text hash, validator fingerprint, mode, and reference identity.
- Test coverage for determinism, stage gating, cache behavior, veto behavior, reward behavior, and API contract.

Excluded from H1:

- Real SysML Pilot, MontiCore, Imandra, Gamma, or nuXmv integration.
- Production database persistence and dashboards.
- Stage 4 structural matching beyond returning the documented default unevaluated fields.
- Stage 5 LLM intent judging beyond returning the documented default unevaluated fields.
- IPT perturbation generation and offline robustness jobs.
- Production performance tuning beyond preserving an async/stateless service shape.

## Architecture

The implementation will use a small package under `src/syvern` with focused modules:

- `api.py`: FastAPI app, `/health`, and `/validate`.
- `models.py`: Pydantic models for requests, responses, errors, violations, config, and internal stage results.
- `normalization.py`: whitespace normalization, text hash, token count, and reference identity.
- `cache.py`: deterministic in-memory cache with exact cache-key construction.
- `adapters/base.py`: backend adapter protocols for parse, resolve, typecheck, and parser agreement.
- `adapters/stub.py`: deterministic H1 stub adapter.
- `rules.py`: rule definitions, rule registry, severity weighting, and anti-gaming categories.
- `veto.py`: hard-boundary veto evaluation.
- `pipeline.py`: Stage 0-3 orchestration and default Stage 4-5 shaping.
- `reward.py`: reward mapping and normalization helpers.
- `settings.py`: default thresholds, weights, caps, and fingerprint values.

H1 will not add a CLI entrypoint. The API and tests are the primary interface.

## Adapter Strategy

H1 must be runnable without external SysML tooling. The stub adapter will be deterministic and deliberately simple:

- Empty or whitespace-only input fails at Stage 0 with a `PARSE_EMPTY_INPUT` error.
- Text containing `syntax_error` fails parse.
- Text containing `unresolved_ref` passes parse but fails resolve with one unresolved reference.
- Text containing `type_error` passes parse/resolve but fails typecheck with one type error.
- Text containing `parser_disagreement` makes the MontiCore stub disagree in `full` mode.
- All other non-empty text parses, resolves, and typechecks successfully.

This gives tests a stable way to exercise the pipeline while preserving the future adapter boundary. The stub behavior is not a SysML parser and must be documented as a harness for H1.

## Pipeline Behavior

The pipeline computes a sample ID from the normalized text hash, then runs the stages:

1. Stage 0 PARSE runs first. If it fails, Stage 1-3 use `reached=false`, `ok=false`, and empty counters. Stage 4-5 remain unevaluated.
2. Stage 1 RESOLVE runs only if parse succeeds. If it fails, Stage 2-3 use `reached=false`, `ok=false`, and empty counters.
3. Stage 2 TYPECHECK runs only if resolve succeeds. Typecheck errors are recorded and make `ok=false`; Stage 3 still runs so constraints and veto can see the parsed model shape.
4. Stage 3 CONSTRAINT runs when parse and resolve succeeded. It records rule violations and severity weights.
5. `online_reward` returns after Stage 3 and leaves Stage 4-5 unevaluated.
6. `full` in H1 runs parser agreement through the second stub adapter and leaves Stage 4-5 unevaluated.
7. `data_filter` returns the same schema as the other modes. Callers use `tier_summary.t0_pass`, `veto.triggered`, and the computed reward to make the filter decision.

`tier_summary.t0_pass` is true only when parse, resolve, typecheck, and constraint are all ok and veto is not triggered. `tier_summary.t1_available` is false in H1 because Stage 4 is outside this slice.

## Rules and Veto

The H1 rule engine includes deterministic starter rules:

- `no_filler_text`: violation when text contains repeated filler markers such as `todo`, `tbd`, or repeated question-mark markers; category `anti_gaming`, severity `error`.
- `no_excessive_repetition`: violation when a normalized token repeats beyond the configured ratio; category `anti_gaming`, severity `error`.
- `minimum_model_signal`: violation when the text has fewer than the configured model-signal tokens after passing parse; category `anti_gaming`, severity `warn`.

The veto module triggers when:

- Token count is below `min_tokens` while the deterministic semantic path otherwise passes.
- Rule violations with category `anti_gaming` and severity `error` are present.
- Parser agreement is explicitly false in `full` mode.

Veto always sets `veto.triggered=true`, records a reason, and forces reward `0.0`.

## Response and Reward

The response schema follows the LLD. H1 will include `reached` fields from the LLD detailed schema, even where the final design excerpt omits them, because the LLD requires distinguishing blocked stages from skipped stages.

Defaults for non-H1 fields:

- `structural.evaluated=false`, numeric scores `0.0`, `ged_accuracy=null`, `matching_policy_id="h1-not-evaluated"`.
- `robustness.stable_at_k=null`, `ipt_consistent=null`.
- `intent.evaluated=false`, `score=null`, `source=null`.
- `monitor.codebleu=null`, `levenshtein=null`.

The reward mapper implements the LLD formula:

- Return `0.0` if veto is triggered.
- Add T0 weights for parse plus parser agreement, resolve, typecheck quality, and constraint quality.
- Add T1 fields using their default H1 values, which contributes `0.0` until Stage 4 exists.
- Subtract hallucination penalty using `structural.hallucinated_elements`.
- Clip to `[0.0, r_max]`.
- Ignore `intent.score`.

## Error Handling

Gateway validation rejects empty request bodies and unsupported modes through Pydantic/FastAPI validation. Empty `text` reaches the adapter only if the request field exists and is blank; it then returns the documented parse error.

Backend failures in H1 are represented by adapter exceptions converted into stage errors with stable codes. Cache writes require a non-empty validator fingerprint. H1 uses a static configured fingerprint and fails application startup if it is empty.

## Testing

Tests will be written before implementation changes for each behavior. Required coverage:

- API returns the documented top-level fields and `meta.mode`.
- Same request returns byte-equivalent JSON on repeated calls except for latency; latency is excluded or normalized in the determinism assertion.
- Cache key includes mode and reference identity.
- `syntax_error` blocks Stage 1-3 with `reached=false`.
- `unresolved_ref` blocks Stage 2-3 with `reached=false`.
- `type_error` records type errors and still reaches constraints.
- Filler or repeated text triggers anti-gaming veto and reward `0.0`.
- `parser_disagreement` in `full` mode triggers veto.
- `intent.score` changes do not affect reward.
- Reward is monotonic across the T0 ladder for representative parse, resolve, typecheck, and constraint outcomes.

## Delivery Criteria

H1 is accepted when:

- The project can install or run its tests with the documented local command.
- `pytest` passes.
- `/validate` can be exercised through FastAPI's test client.
- The code exposes adapter seams for replacing the stub with real SysML backends.
- README explains H1 scope, run/test commands, and the fact that real SysML tooling is not yet integrated.

## Later Milestones

H2 adds real parser cross-checking and `stable@k`. H3 adds Stage 4 structure matching and frozen matching policy. H4 expands veto and adds IPT. H5 adds calibrated intent judging while keeping it out of RLVR reward. H6 adds persistence, observability, reward operations, and monitoring for the semantic-pass by requirement-coverage divergence described in the docs.
