# Bug2 — Empty curated element set falsely vetoed as `degenerate_output`

Status: **Fixed** (Python-only, no Pilot rebuild). Surfaced by the SFT dry-run
over the 95 official SysML v2 reference examples (`examples.zip`,
SysML-v2-Release-2026-04) on 2026-06-20.

## Symptom

Valid SysML v2 models that fully pass the authoritative L0 semantic path
(`parse` + `resolve` + `typecheck` against the standard library) were assigned
**reward 0** via a `degenerate_output` veto, and so were dropped by
`syvern filter`.

Evidence (single-file validation against real Pilot `pilot-0.59.0`):

| Example | parse | resolve | typecheck | curated elements | old verdict |
|---|---|---|---|---|---|
| `Simple Tests/MetadataTest.sysml` | ✅ | ✅ | ✅ | 0 | ❌ `degenerate_output` (reward 0) |
| `Simple Tests/StructuredControlTest.sysml` | ✅ | ✅ | ✅ | 0 | ❌ `degenerate_output` (reward 0) |

Both are correct reference models. Dropping them silently poisons SFT retention.

## Root cause

SYVERN extracts a **curated element subset** — `part, attribute, connection,
requirement, action, state, transition, item, port, interface, constraint,
calc, flow` (`RealPilotBackend.typeOf`). This subset exists for **T1 structural
matching** (F1 / coverage / hallucination), and is deliberately narrow.

The veto (`veto.py`) and a rule (`rules.py`) reused that subset's element
**count** as a proxy for "the model has substance":

```python
# veto.py (before)
if len(elements) < settings.min_elements:
    return VetoSummary(triggered=True, reason="degenerate_output")
# rules.py (before)
if len(elements) < settings.min_elements:
    violations.append(Violation(rule="minimum_element_signal", severity="warn", ...))
```

The subset is the wrong signal for emptiness. Two distinct valid cases extract 0
curated elements:

1. **Constructs outside the subset** — `MetadataTest` is built from `metadata
   def` / `enum def` / metadata usages, none of which are in the whitelist.
2. **Anonymous elements** — `StructuredControlTest` is an anonymous `action { … }`
   with nested attributes; `extractElements` skips elements whose
   `qualifiedName` is blank, so the anonymous action and its nested features are
   dropped.

In both cases the **authoritative L0 already certified the model** as
well-formed and well-typed. An empty *curated* subset is a scoping artifact of
SYVERN's structural lens, not evidence that the model is empty.

## Fix

Stop using the curated structural subset as a substance/degeneracy signal.
Substance is judged by **token content** plus the **authoritative L0 verdict**.

- `veto.py`: removed the `len(elements) < min_elements` clause from
  `degenerate_output`. The token-based guard (`token_count < min_tokens` under
  `semantic_path_passed`) is retained for genuinely trivial output.
- `rules.py`: removed the `minimum_element_signal` rule (same flawed proxy).
- `settings.min_elements` is retained for config/env compatibility but is no
  longer consulted.

This is intentionally a **Python-only** fix. The alternative — broadening the
Java extractor whitelist (and including anonymous elements) — would also change
T1 structural-matching semantics and invalidate the calibrated alignment corpus
(`data/alignment/pilot_real_corpus.jsonl`), and requires a Pilot rebuild. The
degeneracy concern belongs in the Python policy layer, not the structural
extractor.

## Residual limitation (documented, accepted)

Removing the element-count guard means a **valid-but-empty** model (e.g.
`package P {}`, which typechecks with 0 elements and a handful of tokens) now
passes T0 at full reward instead of being vetoed. This is a narrow, low-risk
gap: such a model is *valid* (not gaming), the other anti-gaming rules (filler,
repetition, placeholder names, enumeration padding) still apply, and in `full`
mode an empty model scores 0 on structural F1 / requirement coverage anyway.

The architecturally clean way to recover empty-detection without the curated
subset is for the Pilot to expose a **total user-model element count** (all
`eAllContents` Elements, not just the whitelist) as a separate field, used for
degeneracy while keeping the curated set for structural matching. That is a
Java/API change, deferred until needed.

## Tests

- `tests/test_pipeline.py::test_semantic_pass_with_empty_curated_element_set_is_not_degenerate`
- `tests/test_rules_veto_reward.py::test_semantic_pass_with_empty_curated_element_set_is_not_vetoed`
- `tests/test_rules_veto_reward.py::test_token_trivial_semantic_pass_still_triggers_degenerate_veto`
- `tests/test_rules_veto_reward.py::test_empty_curated_element_set_does_not_produce_element_signal_violation`

The token-based degeneracy guard remains covered by
`tests/test_pipeline.py::test_short_semantic_pass_triggers_degenerate_veto`.

## Verification

Single-file dry-run over the 95 official examples against real Pilot
`pilot-0.59.0`:

| | before any fix | after Bug1 | after Bug2 |
|---|---|---|---|
| `vetoed` | 4 | 2 | **0** |
| `passed` | 78 | 80 | **82** |

The remaining 13 `t0_failed` are cross-file import examples; validating per
folder (all `.sysml` in a folder merged into one model — the correct unit)
yields **24/24** example folders passing.
