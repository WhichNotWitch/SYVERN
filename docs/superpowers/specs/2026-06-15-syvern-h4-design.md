# SYVERN H4 Anti-Gaming And IPT Design

## Purpose

H4 adds the deterministic anti-gaming boundary described in the SYVERN design documents. H1-H3 made the T0 core, H2 parser robustness, and H3 reference-based structural matching executable. H4 hardens that harness against reward hacking by expanding veto rules and adding a deterministic IPT consistency check.

The milestone keeps the online reward path fast and reproducible. Anti-gaming vetoes remain deterministic and run inside the existing Stage 3 constraint/veto boundary. IPT is a conditional full-mode robustness signal: it evaluates supplied equivalent perturbation samples against the same frozen structural policy, then records whether the generated structure is stable under those perturbations.

## Scope

Included in H4:

- Stronger anti-gaming rules for degenerate output, placeholder or formatting filler, excessive repetition, and enumeration-style structure.
- A stable veto reason taxonomy for hard reward-zeroing cases.
- A deterministic IPT checker that consumes caller-supplied perturbation samples.
- `robustness.ipt_consistent` evaluation in `full` mode when a reference and perturbations are supplied and T0 passes without veto.
- Reward integration through the existing `w6` term, only after T0 passes and IPT consistency is true.
- API and pipeline forwarding for perturbation samples.
- Cache behavior that distinguishes perturbation identity.
- README updates describing H4 scope, inputs, and deterministic limits.

Excluded from H4:

- LLM-generated perturbations.
- Human equivalence verification for perturbations.
- Real SysML semantic equivalence checking.
- Stage 5 intent judging.
- Persistent storage, dashboards, or production monitoring scatter plots.
- Running IPT in `online_reward` or `data_filter` mode.
- Changing H3 structural matching from exact frozen matching to fuzzy or semantic matching.

## Architecture

H4 adds one focused module and extends the existing validation path:

- `ipt.py`: validates perturbation inputs, runs exact structural matching for each perturbation sample, and returns a deterministic IPT result.
- `rules.py`: adds H4 anti-gaming predicates that emit `Violation(category="anti_gaming", severity="error")`.
- `veto.py`: maps hard anti-gaming conditions to stable veto reasons while preserving existing parser-disagreement and degenerate-output behavior.
- `models.py`: adds request fields for `perturbations` and enough response detail to keep IPT results auditable without changing the top-level schema shape.
- `pipeline.py`: forwards perturbations, evaluates IPT only for eligible `full` requests, and stores the result in `robustness.ipt_consistent`.
- `api.py`: includes perturbation identity in the validation cache key and forwards perturbations to the pipeline.
- `settings.py`: adds H4 thresholds and updates the validator fingerprint.
- `README.md`: documents the H4 deterministic anti-gaming and IPT behavior.

The design keeps anti-gaming and IPT separate. Veto answers "must this sample receive zero reward?" IPT answers "is this full-mode structural result stable under caller-supplied equivalent perturbations?"

## Request Shape

H4 extends validation requests with an optional `perturbations` field:

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
  "perturbations": [
    "attribute vehicle.mass part vehicle.engine",
    "part vehicle.engine attribute vehicle.mass"
  ]
}
```

Rules:

- `perturbations` is optional.
- Missing or empty perturbations keep `robustness.ipt_consistent=null`.
- Perturbation entries are generated model texts, not natural-language requirement rewrites.
- H4 assumes callers only supply perturbations they consider semantically equivalent. It does not prove equivalence.
- Unknown request fields continue to follow the existing Pydantic model behavior.

## Anti-Gaming Veto Rules

H4 keeps existing hard-veto behavior and adds deterministic heuristics.

Hard veto reasons:

- `parser_disagreement`: `full` mode cross-parser agreement fails.
- `degenerate_output`: T0 passes but the generated model is too short or has too few extracted elements.
- `anti_gaming_rule`: an explicit anti-gaming rule with severity `error` fires.

Anti-gaming rule IDs:

- `no_filler_text`: placeholder tokens such as `todo`, `tbd`, `dummy`, `filler`, `???`, or obvious placeholder formatting are present.
- `no_excessive_repetition`: one normalized token exceeds the configured repetition ratio.
- `minimum_model_signal`: the text has fewer than `min_tokens` tokens; this remains a warn-level violation, while `veto.py` owns the hard `degenerate_output` decision after T0 passes.
- `minimum_element_signal`: T0 passes but extracted element count is lower than `min_elements`.
- `no_enumeration_gaming`: repeated sibling-like elements exceed the configured enumeration ratio.
- `no_placeholder_names`: generated element names are placeholder-like, such as `item1`, `item2`, `foo`, `bar`, `example`, or `placeholder`.

The rules intentionally favor false negatives over false positives for H4. If a pattern is ambiguous, it should be a warning or omitted until a stronger deterministic rule exists. Hard veto is a reward boundary, not a style linter.

## Enumeration Detection

The H4 enumeration heuristic catches shallow instance lists that appear to game element counts without adding structure.

For generated element summaries:

- Group elements by `(type, base_name)`, where `base_name` removes a trailing numeric suffix from the last qualified-name segment.
- Count groups with at least `settings.enum_min_group_size` members.
- If the largest such group accounts for more than `settings.enum_ratio` of generated elements, emit `no_enumeration_gaming`.

Examples:

- `part wheel1 part wheel2 part wheel3 part wheel4` can trigger enumeration gaming.
- `part vehicle.engine attribute vehicle.mass connection vehicle.power_link` does not trigger enumeration gaming.

This is a deterministic stub heuristic. It is not a complete SysML topology analysis.

## IPT Eligibility

IPT runs only when all of the following are true:

- Request mode is `full`.
- A non-null `reference` is supplied.
- `perturbations` is a non-empty list.
- Parse, resolve, and typecheck pass for the original text.
- Constraint stage is reached and passes for the original text.
- Veto has not triggered for the original text.
- Stage 4 structural matching has evaluated for the original text.

When IPT is not eligible, `robustness.ipt_consistent=null`.

Each perturbation sample is validated through the same deterministic element extraction and structural matcher. H4 does not run full nested pipeline validation for every perturbation, because this milestone is a low-cost deterministic harness. Future milestones can add deeper perturbation validation if needed.

## IPT Algorithm

For each perturbation text:

1. Extract generated elements with the same H2/H3 stub extractor.
2. Run `match_structural(perturbation_elements, reference, settings)`.
3. Record the perturbation structural F1.
4. Compare the F1 with `settings.ipt_threshold`.

Result:

- `ipt_consistent=true` when every perturbation has `f1 >= settings.ipt_threshold`.
- `ipt_consistent=false` when at least one perturbation falls below the threshold.
- `ipt_consistent=null` when IPT is not eligible or no perturbations are supplied.

The default `ipt_threshold` is `1.0` for H4 because H3 uses exact frozen matching. This makes the smoke behavior clear: exact equivalent perturbations pass; missing or renamed reference elements fail.

## Reward Behavior

H4 uses the reward formula already present in `reward.py`:

- Veto still returns reward `0.0`.
- T0 terms remain the dominant reward path.
- H3 `w4` and `w5` continue to use structural F1 and requirement coverage after T0 passes.
- H4 activates the existing `w6` term only when T0 passes and `robustness.ipt_consistent is True`.
- `ipt_consistent=False` adds no positive reward. It does not subtract reward in H4; the structural and veto terms already handle deterministic failures.

H4 may set the default `w6` to `0.0` and test reward behavior with an explicit `RewardWeights(w6=...)`. This preserves current reward totals unless callers intentionally enable the IPT positive term.

## Cache And Determinism

The validation cache key must include perturbation identity so that the same text/reference with different perturbations cannot reuse a stale IPT result.

Perturbation identity is deterministic:

- Normalize each perturbation text using the existing whitespace normalization.
- Preserve list order, because the response may later expose per-perturbation details.
- Hash or serialize the normalized list into the cache key.
- Missing perturbations and an empty list share the "no IPT" identity.

Repeated calls with identical text, mode, reference identity, fingerprint, and perturbation identity must return the same response except for `meta.cache_hit`.

## Error Handling

- Missing perturbations: IPT remains unevaluated; no error is returned.
- Empty perturbation list: IPT remains unevaluated; no error is returned.
- Blank perturbation entry: counts as an inconsistent perturbation if IPT is otherwise eligible.
- Malformed reference: follows H3 structural parsing rules.
- Original request veto: IPT remains unevaluated.
- Perturbation structural match with empty generated elements: F1 is `0.0`, so IPT is inconsistent.

## Testing

Required H4 coverage:

- Filler and placeholder markers trigger anti-gaming violations.
- Excessive repetition triggers an anti-gaming violation.
- T0-passing but too-short text triggers `degenerate_output`.
- T0-passing text with fewer than `min_elements` extracted elements triggers `degenerate_output`.
- Enumeration-style generated elements trigger `no_enumeration_gaming` and reward zero.
- Parser disagreement still triggers `parser_disagreement` and reward zero.
- `full` mode with reference and equivalent perturbations sets `robustness.ipt_consistent=true`.
- `full` mode with at least one structurally different perturbation sets `robustness.ipt_consistent=false`.
- Missing perturbations leave `ipt_consistent=null`.
- `online_reward` and `data_filter` do not run IPT.
- T0 failure or veto prevents IPT evaluation.
- Reward includes the `w6` term only when T0 passes and IPT is true.
- API cache distinguishes different perturbation lists.
- Existing H1-H3 tests continue to pass.

## Delivery Criteria

H4 is accepted when:

- `pytest` passes.
- `/validate` in `full` mode with reference and equivalent perturbations returns `robustness.ipt_consistent=true`.
- `/validate` in `full` mode with a structurally different perturbation returns `robustness.ipt_consistent=false`.
- Vetoed samples always return reward `0.0`.
- `online_reward` remains deterministic and does not run IPT.
- README documents H4 anti-gaming and IPT limits.

## Later Milestones

H5 adds Stage 5 intent judging, calibration, and human/LLM preference-facing signals while keeping those signals out of deterministic RLVR reward. H6 adds persistence, monitoring, reward operations, and the `semantic_pass` by `requirement_coverage` divergence checks described in the design documents.
