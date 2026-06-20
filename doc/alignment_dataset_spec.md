# SYVERN Alignment Dataset Spec (Phase 1 · human-truth)

This spec defines the **manually annotated** SysML v2 alignment dataset used to
make the T0 validator trustworthy (Phase 1). Ground truth is decided by a
human against the SysML v2 language semantics — **not** copied from the Pilot's
output. The dataset is then used to *measure* where Pilot/SYVERN agree or
disagree with truth.

- Seed template: [`data/alignment/alignment_seed_template.jsonl`](../data/alignment/alignment_seed_template.jsonl) (10 cases)
- Target: `manual_v1.jsonl` (60 cases) — expand the template to the quota below
- Checker: [`scripts/check_alignment_dataset.py`](../scripts/check_alignment_dataset.py)

## 1. Record schema (one JSON object per line)

Truth is recorded as **booleans**, not exact integer counts. Exact counts (e.g.
"3 unresolved refs") are brittle to label by hand and produce false
disagreements that are not real validity errors; ok-ness is what the data_filter
gate actually consumes.

| field | type | required | meaning |
|---|---|---|---|
| `case_id` | string | ✅ | unique id, e.g. `valid_001` |
| `category` | string | ✅ | one of `valid` `syntax` `unresolved` `type` `nested` |
| `text` | string | ✅ | the SysML v2 source (real, self-contained) |
| `parse_ok` | bool | ✅ | does it lex/parse? |
| `resolve_ok` | bool \| null | ✅ | do all references resolve? `null` if parse failed (stage not reached) |
| `typecheck_ok` | bool \| null | ✅ | does it satisfy KerML/SysML constraints? `null` if parse or resolve failed |
| `keep_expected` | bool | ✅ | **full-gate truth**: should this enter SFT? (= clean T0) |
| `expected_elements` | list \| null | ⬜ | optional structural truth (Phase 1 leaves `null`; structural matching is cut) |
| `notes` | string | ⬜ | one-line human rationale for the truth |

### Cascade rule (stage reachability)

Stages gate left-to-right. A stage that is not reached must be labelled `null`:

- `parse_ok = false` ⇒ `resolve_ok = null`, `typecheck_ok = null`
- `resolve_ok = false` ⇒ `typecheck_ok = null`

### `keep_expected` rule

`keep_expected = (parse_ok and resolve_ok and typecheck_ok)`. A model enters SFT
only if it is clean through T0. The checker enforces this equality, so
`keep_expected` is a redundant-but-explicit cross-check of the stage labels and
the anchor for **1.3b full-gate validation** (compare `data_filter_pass` against
`keep_expected`).

## 2. Category ⇄ truth contract

The checker enforces that each category has exactly this truth shape:

| category | parse_ok | resolve_ok | typecheck_ok | keep_expected |
|---|---|---|---|---|
| `valid` | true | true | true | true |
| `nested` | true | true | true | true |
| `syntax` | false | null | null | false |
| `unresolved` | true | false | null | false |
| `type` | true | true | false | false |

`nested` is semantically `valid` but exercises depth / scale gradients (deep
containment, many elements, connections) to stress element extraction and
resolution. Keep `nested` cases meaningfully larger/deeper than `valid` ones.

## 3. Quota

| profile | valid | syntax | unresolved | type | nested | total |
|---|---|---|---|---|---|---|
| `seed` (template) | 2 | 2 | 2 | 2 | 2 | 10 |
| `manual_v1` (target) | 22 | 10 | 10 | 10 | 8 | 60 |

`check_alignment_dataset.py --in <file> --profile manual_v1` must report **0
errors** and a **full quota** before the set is adopted.

## 4. Authoring rules

1. **Human-decides-first.** Label truth from the language semantics. You may
   *sanity-check* against a running Pilot, but a Pilot disagreement is a finding
   to record (Phase 1.3 "发现清单"), not a reason to flip the label.
2. **Real, self-contained SysML v2.** Each `text` must stand alone (no
   cross-file imports); validate as a single document.
3. **No stub trigger words.** `text` must not contain the stub adapter markers
   `syntax_error`, `unresolved_ref`, `type_error`, `parser_disagreement` — they
   corrupt stub-based smoke tests. The checker flags these (warning; error under
   `--strict`).
4. **One defect per error case.** A `type` case should fail *only* typecheck; an
   `unresolved` case should fail *only* resolve. Verify the defect is isolated
   (e.g. a `type` case must still resolve cleanly).
5. **Unique `case_id`.** Duplicate text is flagged (warning).

### Notes on what Pilot 0.59.0 actually flags (so labels are realistic)

Confirmed while building the seed template:

- Reliable **type** errors: specializing across metaclasses, e.g.
  `part def P :> ScalarValues::Integer;` ("Cannot specialize attribute
  definition") or `attribute def A :> SomePartDef;`.
- **Not** flagged as type errors by 0.59.0 (do NOT use as `type` cases):
  assigning a Boolean to an Integer attribute; redefining a feature with an
  unrelated type; reversed/widened multiplicity. These pass typecheck.

## 5. Downstream dependencies (later phases)

- **1.3** `syvern align` currently consumes integer truth
  (`unresolved_refs`/`type_errors`) and does exact-count matching. Consuming
  this bool schema requires extending `alignment.py` to compare ok-ness
  (`resolve_ok`/`typecheck_ok`). Tracked for 1.3.
- **1.3b** full-gate validation: run `mode=data_filter` over the set and compare
  `data_filter_pass` vs `keep_expected` and `veto.reason` — this is the layer
  `align` does **not** cover (L1 rules / veto / reward), where Bug1/Bug2 lived.
