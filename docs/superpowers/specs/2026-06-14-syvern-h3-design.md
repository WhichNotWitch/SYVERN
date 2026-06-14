# SYVERN H3 Structural Matching Design

## Purpose

H3 adds the deterministic Stage 4 structural matching layer described in the SYVERN documents. H1/H2 made T0 validation, parser agreement, and batch robustness executable. H3 makes the T1 structural fields meaningful when a fixed reference model is supplied and a frozen matching policy is used.

The milestone must keep the online reward path fast and deterministic. Structural matching is conditional: it runs only when the request mode and reference make Stage 4 applicable. It does not introduce LLM semantic alignment, IPT, real SysML tooling, or persistence.

## Scope

Included in H3:

- A deterministic structural matcher for generated model elements against reference elements.
- A frozen matching policy identified by `matching_policy_id="h3-frozen-exact-v1"`.
- `full` mode Stage 4 evaluation when T0 passes and `reference` is present.
- `precision`, `recall`, `f1`, `requirement_coverage`, and `hallucinated_elements` calculations.
- `ged_accuracy=null`, reserved for a future graph edit distance implementation.
- Reward integration through the existing T1 terms already present in `reward.py`.
- Cache behavior that continues to distinguish reference identity.
- API and pipeline tests for evaluated and unevaluated Stage 4 behavior.
- README updates describing H3 scope and reference shape.

Excluded from H3:

- Real SysML Pilot, MontiCore, or graph extraction integration.
- Fuzzy matching, synonym dictionaries, and LLM semantic alignment.
- GED calculation.
- IPT perturbation and anti-enumeration hard veto.
- Stage 5 intent judging.
- Database persistence, dashboards, or monitoring scatter plots.
- Running Stage 4 in `online_reward` or `data_filter` mode.

## Architecture

H3 adds one focused module and keeps the existing API shape:

- `structural.py`: reference parsing, generated element extraction, exact matching, requirement coverage, hallucination count, and `StructuralSummary` construction.
- `pipeline.py`: passes the optional reference through validation, runs Stage 4 only for eligible `full` requests, and leaves Stage 4 unevaluated otherwise.
- `api.py`: forwards `reference` to the pipeline while preserving the existing cache key and response model.
- `settings.py`: changes the default matching policy from the H1 placeholder to the H3 frozen policy.
- `README.md`: documents the H3 reference format and mode behavior.

The H3 matcher will reuse `ElementSummary` and the H2 stub element extractor rather than adding a second text parser. This keeps the generated element view consistent between L0' agreement and Stage 4.

## Reference Format

H3 accepts a simple JSON reference model:

```json
{
  "elements": [
    {"type": "part", "qualified_name": "vehicle.engine"},
    {"type": "attribute", "qualified_name": "vehicle.mass"}
  ],
  "requirements": ["req.power", "req.mass"],
  "coverage": {
    "req.power": ["vehicle.engine"],
    "req.mass": ["vehicle.mass"]
  }
}
```

Rules:

- `elements` is the reference element set. Each item uses the existing `ElementSummary` normalization.
- `requirements` is an optional list of reference requirement IDs.
- `coverage` maps requirement IDs to reference element qualified names that satisfy the requirement.
- Unknown top-level fields are ignored.
- Missing `elements` is treated as an empty reference model.
- Invalid element objects are ignored rather than failing the whole request; H3 is a scoring layer and does not break otherwise valid T0 validation.

Requirement IDs and coverage target names are lower-cased and whitespace-normalized. Coverage target names match reference element `qualified_name` values.

## Matching Policy

The frozen H3 policy is `h3-frozen-exact-v1`.

Policy rules:

- Normalize `type` and `qualified_name` with `ElementSummary`.
- Compare generated and reference elements by exact `(type, qualified_name)` pairs.
- Use multiset semantics: duplicate generated or reference elements are counted.
- Do not strip suffixes, apply edit distance, use synonyms, or call a semantic judge.
- Preserve deterministic behavior across repeated calls.

This is intentionally narrower than the full design document. It establishes the T1 deterministic baseline before future soft matching work.

## Stage 4 Eligibility

Stage 4 runs only when all of the following are true:

- Request mode is `full`.
- A non-null `reference` is supplied.
- Parse, resolve, and typecheck all pass.
- Constraint stage is reached.
- Veto has not triggered.

When Stage 4 is not eligible, `structural.evaluated=false` and numeric fields stay at their default `0.0` values. This includes `online_reward`, `data_filter`, missing reference, parse failure, resolve failure, typecheck failure, and hard veto cases.

H3 keeps Stage 5 intent unevaluated.

## Metrics

Let `G` be the generated element multiset and `R` be the reference element multiset.

- `matched = multiset_intersection_count(G, R)`
- `precision = matched / len(G)`; if `len(G)==0`, precision is `0.0`.
- `recall = matched / len(R)`; if `len(R)==0`, recall is `0.0`.
- `f1 = 2 * precision * recall / (precision + recall)`; if the denominator is zero, F1 is `0.0`.
- `hallucinated_elements = len(G) - matched`.
- `ged_accuracy = null`.

Requirement coverage:

- If `requirements` is empty, `requirement_coverage=0.0`.
- A requirement is covered when at least one of its coverage target names appears in a matched generated/reference element pair.
- `requirement_coverage = covered_requirements / len(requirements)`.
- Coverage targets that do not exist in reference elements do not count.

## Reward Behavior

H3 does not change reward weights or formula structure. `reward.py` already adds:

- `w4 * structural.f1`
- `w5 * structural.requirement_coverage`

only when T0 has passed. H3 simply supplies non-default structural values when Stage 4 is evaluated. Veto continues to force reward `0.0`.

This keeps T1 as a downgraded auxiliary reward and preserves the HLD/LLD boundary that T0 remains the deterministic core.

## Cache And Determinism

The existing cache key includes reference identity. H3 relies on that behavior so the same text with two different references can produce different structural scores without cache collision.

The pipeline must pass `reference` into validation before the response is cached. Repeated calls with identical normalized text, mode, fingerprint, and reference identity must return the same response except for `meta.cache_hit`.

## Error Handling

- Missing reference in `full` mode: Stage 4 stays unevaluated; no error is returned.
- Empty reference elements: Stage 4 evaluates when otherwise eligible, but precision, recall, F1, and requirement coverage are `0.0`.
- Malformed element entries inside `reference.elements`: ignored.
- Non-list `reference.elements` or `reference.requirements`: treated as empty.
- Non-dict `reference.coverage`: treated as empty.
- Typecheck failure or veto: Stage 4 remains unevaluated.

## Testing

Required H3 coverage:

- Structural extraction reuses H2 element syntax for generated text.
- Exact match produces `precision=1.0`, `recall=1.0`, `f1=1.0`.
- Missing generated elements reduce recall and F1.
- Extra generated elements reduce precision and increase `hallucinated_elements`.
- Duplicate elements use multiset semantics.
- Requirement coverage counts requirements whose target elements are matched.
- `full` mode with reference evaluates structural fields.
- `full` mode without reference keeps structural unevaluated.
- `online_reward` and `data_filter` do not evaluate Stage 4.
- T0 failure or veto prevents Stage 4 evaluation.
- Reward includes H3 T1 terms only when T0 passes and Stage 4 evaluated.
- Cache distinguishes different references.
- Existing H1/H2 tests continue to pass.

## Delivery Criteria

H3 is accepted when:

- `pytest` passes.
- `/validate` in `full` mode with reference returns `structural.evaluated=true`.
- `/validate` without reference remains backward-compatible and leaves structural fields unevaluated.
- `online_reward` remains high-throughput and does not run Stage 4.
- The frozen matching policy is visible in `structural.matching_policy_id`.
- README explains the H3 reference shape and deterministic matching limits.

## Later Milestones

H4 adds IPT perturbation and stronger anti-gaming boundaries. H5 adds calibrated intent judging and semantic alignment work while keeping it out of deterministic RLVR reward. H6 adds persistence, monitoring, and reward operations including the `semantic_pass` by `requirement_coverage` divergence checks described in the docs.
