# SYVERN H2 Cross-Parser Robustness Design

## Purpose

H2 extends the H1 executable validation service with the robustness features called out in the project documents: independent L0' parser agreement and `pass@k` / `stable@k` aggregation. The goal is to make cross-parser and multi-sample robustness observable and testable without requiring real SysML Pilot or MontiCore installations yet.

H2 remains a deterministic harness milestone. It strengthens the adapter contracts and API surface so later milestones can replace local stubs with real tools while preserving response semantics, reward behavior, cache determinism, and the H1 anti-gaming boundaries.

## Scope

Included in H2:

- Extend parser adapter results with normalized element summaries.
- Implement parser agreement as `(parse_ok == parse_ok_prime) and element_summary_multiset_equal`.
- Keep L0' parser agreement enabled in `full` mode.
- Preserve `online_reward` as the high-throughput path that does not call the second parser by default.
- Add deterministic robustness aggregation over multiple samples.
- Add `pass_at_k` and `stable_at_k` to aggregate output.
- Add a batch validation API for robustness evaluation while keeping `/validate` backward-compatible.
- Add tests for element-summary comparison, parser disagreement veto, batch metrics, cache behavior, and API contracts.
- Update README with H2 behavior and examples.

Excluded from H2:

- Real SysML Pilot or MontiCore process integration.
- Structural matching against a reference model.
- IPT perturbation generation.
- LLM or human intent judging.
- Persistent storage, dashboards, and production observability.
- Changing H1 reward weights or letting intent scores influence reward.

## Architecture

H2 keeps the existing H1 package structure and adds only focused pieces:

- `models.py`: add element-summary and batch request/response models.
- `adapters/base.py`: include `element_summary` in parse results and expose parser-summary comparison through adapter contracts.
- `adapters/stub.py`: generate deterministic element summaries for both Pilot and MontiCore stubs.
- `pipeline.py`: compare parser summaries in `full` mode and expose a batch validation method.
- `robustness.py`: compute semantic pass, `pass_at_k`, and `stable_at_k` from validation responses.
- `api.py`: keep `POST /validate` unchanged and add `POST /validate_batch`.
- `README.md`: document H2 scope, markers, and commands.

The implementation should follow the H1 style: small modules, typed Pydantic models at boundaries, deterministic stubs, and pytest coverage before changing behavior.

## Element Summaries

An element summary is the normalized representation used for parser agreement:

```json
{ "type": "part", "qualified_name": "vehicle.engine" }
```

Rules:

- `type` and `qualified_name` are lower-cased and whitespace-normalized.
- Empty names are ignored.
- The comparison is a multiset comparison, so duplicate normalized elements are significant.
- Ordering in adapter output must not affect agreement.
- Parse failures return an empty summary.

The deterministic H2 stub extracts summaries from lightweight textual markers that are easy to test:

- `part <name>`
- `attribute <name>`
- `connection <name>`
- `requirement <name>`
- `item <name>`
- `action <name>`

Names may include letters, numbers, underscores, hyphens, and dots. This is a harness grammar, not a SysML parser.

## Parser Agreement

In `full` mode, the pipeline runs the Pilot stub and the MontiCore stub independently. It then sets `stage.parse.parser_agreement` from this predicate:

```text
(pilot_parse.ok == monticore_parse.ok)
and
multiset(pilot_parse.element_summary) == multiset(monticore_parse.element_summary)
```

If both parsers fail in the same way, agreement may be true, but the sample still fails the parse stage because `parse.ok=false`. If parse status differs or summaries differ, agreement is false.

Stub behavior for tests:

- `parser_disagreement` makes the MontiCore stub disagree on parse status.
- `summary_disagreement` keeps parse status aligned but changes the MontiCore element summary.
- Normal text produces matching summaries from both stubs.

A false `parser_agreement` in `full` mode triggers the existing parser-disagreement veto and forces reward to `0.0`.

## Robustness Aggregation

H2 adds batch robustness for a list of generated samples that belong to the same prompt or task.

Definitions:

- `semantic_pass = parse.ok and resolve.ok and typecheck.ok`.
- `pass_at_k = 1.0` when at least one sample has `semantic_pass=true`; otherwise `0.0`.
- `stable_at_k = semantic_pass_count / k`.
- `k = len(samples)`.

Empty sample lists are rejected at request validation. The batch result records the aggregate metrics once at the batch level. Individual `/validate` responses remain unchanged except for any existing `robustness.stable_at_k`, which stays `null` for single-sample validation.

## API Behavior

Existing endpoint:

```text
POST /validate
Req:  { text, reference?, mode, k? }
Resp: ValidationResponse
```

H2 must preserve this contract and H1 cache behavior.

New endpoint:

```text
POST /validate_batch
Req:  { texts: string[], reference?, mode: "online_reward"|"full"|"data_filter" }
Resp: {
  sample_count: int,
  pass_at_k: float,
  stable_at_k: float,
  responses: ValidationResponse[],
  meta: { mode: str, validator_fingerprint: str }
}
```

The batch endpoint validates each text through the same `ValidationPipeline` and cache path used by `/validate`. This avoids a second implementation of validation logic and keeps repeated samples deterministic.

The optional single-request `k` field remains accepted for schema compatibility, but H2 does not use it on `/validate`. Batch `k` is derived from `len(texts)` to avoid mismatch ambiguity.

## Cache And Determinism

The H1 cache key already includes normalized text, validator fingerprint, mode, and reference identity. H2 continues to use this key for each individual validation in a batch. Aggregate batch metrics are computed from the returned responses and are not cached separately.

Parser-summary extraction must be deterministic. Response ordering in `/validate_batch` must match request ordering.

## Error Handling

- Empty batch request: rejected by Pydantic validation.
- Blank text inside a batch: handled the same way as `/validate` blank text and contributes a failed semantic pass.
- Adapter exceptions: converted through the existing stage error path.
- `summary_disagreement` in `full` mode: represented as `parser_agreement=false`, not as a new parse error.
- `summary_disagreement` in `online_reward` mode: does not run L0' and therefore does not trigger parser-disagreement veto.

## Testing

Required H2 coverage:

- Element summaries normalize case, whitespace, and ordering.
- Multiset comparison treats duplicates as significant.
- `full` mode detects `summary_disagreement` and triggers veto with reward `0.0`.
- `online_reward` does not run the MontiCore stub and does not trigger parser-disagreement veto for `summary_disagreement`.
- `parser_disagreement` still triggers the H1 veto behavior in `full` mode.
- Batch validation returns responses in request order.
- Batch validation reports `pass_at_k=1.0` when any sample has semantic pass.
- Batch validation reports `stable_at_k=count_semantic_pass/k`.
- Empty batch requests fail validation.
- Repeated batch calls produce deterministic aggregate metrics.
- Existing H1 tests continue to pass.

## Delivery Criteria

H2 is accepted when:

- `pytest` passes.
- `POST /validate` remains backward-compatible with H1 behavior.
- `POST /validate_batch` returns deterministic `pass_at_k` and `stable_at_k`.
- `full` mode parser agreement uses normalized element-summary multiset equality.
- README explains H2 scope, marker syntax, and example requests.
- No real external SysML tooling is required to run the project.

## Later Milestones

H3 will use richer element and relationship extraction for structural matching. H4 will add IPT perturbation and stronger anti-gaming checks. H5 will add calibrated intent judging. H6 will add persistent reward operations, monitoring, and production observability.
