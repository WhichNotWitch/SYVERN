# SYVERN Element Set Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ParseResult.element_summary` the single source of truth for downstream element consumers instead of re-running the stub regex extractor on raw text.

**Architecture:** `ValidationPipeline.validate()` already calls `self.pilot.parse(text)` once. Thread that `parse_result.element_summary` into rules, veto, structural matching, and `_finish()`. For IPT, parse each perturbation through the same pilot adapter in the pipeline, then make `evaluate_ipt()` a pure function over element sets.

**Tech Stack:** Python 3.11+, pytest, Pydantic models, existing SYVERN adapter/pipeline modules.

---

## File Structure

- Modify `src/syvern/pipeline.py`: pass parser element summaries through the pipeline and parse IPT perturbations via `self.pilot`.
- Modify `src/syvern/rules.py`: change `evaluate_rules(text, settings)` to `evaluate_rules(text, elements, settings)`.
- Modify `src/syvern/veto.py`: change `evaluate_veto(...)` to accept `elements`.
- Modify `src/syvern/ipt.py`: change `evaluate_ipt()` to accept `original_elements` and `perturbation_element_sets`.
- Modify `tests/test_rules_veto_reward.py`: migrate direct rule/veto calls to pass element fixtures.
- Modify `tests/test_ipt.py`: migrate IPT tests from raw text to `ElementSummary` lists.
- Add `tests/test_element_set_wiring.py`: integration tests proving downstream consumers use adapter-produced elements.
- Optionally modify `README.md` / `STATUS.md`: document that element set wiring is complete.

## Task 1: Add Element-Source Regression Tests

**Files:**
- Create: `tests/test_element_set_wiring.py`

- [ ] **Step 1: Write fake adapters and structural source test**

Create `tests/test_element_set_wiring.py`:

```python
from syvern.adapters.base import ParseResult, ResolveResult, TypecheckResult
from syvern.models import ElementSummary, ErrorDetail
from syvern.pipeline import ValidationPipeline


class FakeElementAdapter:
    name = "fake-element-adapter"

    def __init__(self) -> None:
        self.parse_calls: list[str] = []

    def fingerprint(self) -> str:
        return "fake-element-adapter@1"

    def parse(self, text: str) -> ParseResult:
        self.parse_calls.append(text)
        if "broken" in text:
            return ParseResult(
                ok=False,
                errors=[
                    ErrorDetail(
                        stage="parse",
                        code="PARSE_BROKEN",
                        message="synthetic syntax-aware failure",
                    )
                ],
                element_summary=[],
            )
        if "wing" in text:
            return ParseResult(
                ok=True,
                errors=[],
                element_summary=[
                    ElementSummary(type="part", qualified_name="vehicle.wing"),
                    ElementSummary(type="attribute", qualified_name="vehicle.span"),
                ],
            )
        return ParseResult(
            ok=True,
            errors=[],
            element_summary=[
                ElementSummary(type="part", qualified_name="vehicle.engine"),
                ElementSummary(type="attribute", qualified_name="vehicle.mass"),
            ],
        )

    def resolve(self, text: str) -> ResolveResult:
        return ResolveResult(ok=True, unresolved_refs=0, errors=[])

    def typecheck(self, text: str) -> TypecheckResult:
        return TypecheckResult(ok=True, type_errors=0, errors=[])


class AgreeingMontiCoreAdapter:
    name = "agreeing-monticore"

    def fingerprint(self) -> str:
        return "agreeing-monticore@1"

    def parse(self, text: str) -> ParseResult:
        return ParseResult(ok=True, errors=[], element_summary=[])

    def resolve(self, text: str) -> ResolveResult:
        return ResolveResult(ok=True, unresolved_refs=0, errors=[])

    def typecheck(self, text: str) -> TypecheckResult:
        return TypecheckResult(ok=True, type_errors=0, errors=[])

    def parser_agrees(self, text: str, pilot) -> bool:
        return True


def _reference() -> dict:
    return {
        "elements": [
            {"type": "part", "qualified_name": "vehicle.engine"},
            {"type": "attribute", "qualified_name": "vehicle.mass"},
        ],
    }


def test_pipeline_consumes_adapter_elements_for_rules_veto_and_structural():
    response = ValidationPipeline(
        pilot_adapter=FakeElementAdapter(),
        monticore_adapter=AgreeingMontiCoreAdapter(),
    ).validate(
        "plain words with no sysml keywords",
        mode="full",
        reference=_reference(),
    )

    assert response.veto.triggered is False
    assert {violation.rule for violation in response.stage.constraint.violations} == set()
    assert response.structural.evaluated is True
    assert response.structural.f1 == 1.0
```

- [ ] **Step 2: Run the test to verify current failure**

Run: `python -m pytest tests/test_element_set_wiring.py::test_pipeline_consumes_adapter_elements_for_rules_veto_and_structural -q -p no:cacheprovider`

Expected: FAIL because current business code re-extracts zero elements from raw text and triggers `degenerate_output`.

## Task 2: Pass Main Parse Elements Through Pipeline, Rules, And Veto

**Files:**
- Modify: `src/syvern/pipeline.py`
- Modify: `src/syvern/rules.py`
- Modify: `src/syvern/veto.py`
- Modify: `tests/test_rules_veto_reward.py`

- [ ] **Step 1: Update `rules.py` to accept explicit elements**

Change imports in `src/syvern/rules.py`:

```python
from syvern.models import ElementSummary, Violation
```

Remove:

```python
from syvern.adapters.stub import extract_element_summary
```

Change the signature:

```python
def evaluate_rules(
    text: str,
    elements: list[ElementSummary],
    settings: SyvernSettings,
) -> list[Violation]:
    normalized = normalize_ws(text).lower()
    violations: list[Violation] = []
```

Delete the line:

```python
    elements = extract_element_summary(text)
```

- [ ] **Step 2: Update `veto.py` to accept explicit elements**

Change imports in `src/syvern/veto.py`:

```python
from syvern.models import ElementSummary, VetoSummary, Violation
```

Remove:

```python
from syvern.adapters.stub import extract_element_summary
```

Change the signature and element check:

```python
def evaluate_veto(
    *,
    text: str,
    elements: list[ElementSummary],
    settings: SyvernSettings,
    semantic_path_passed: bool,
    parser_agreement: bool | None,
    violations: list[Violation],
) -> VetoSummary:
    if parser_agreement is False:
        return VetoSummary(triggered=True, reason="parser_disagreement")

    if any(v.category == "anti_gaming" and v.severity == "error" for v in violations):
        return VetoSummary(triggered=True, reason="anti_gaming_rule")

    if semantic_path_passed:
        if token_count(text) < settings.min_tokens:
            return VetoSummary(triggered=True, reason="degenerate_output")
        if len(elements) < settings.min_elements:
            return VetoSummary(triggered=True, reason="degenerate_output")

    return VetoSummary(triggered=False, reason=None)
```

- [ ] **Step 3: Update `pipeline.py` imports and `_finish()` signature**

Change the stub import:

```python
from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter
```

Add `ElementSummary` to the `syvern.models` import block.

Change `_finish()`:

```python
    def _finish(
        self,
        *,
        text: str,
        elements: list[ElementSummary],
        mode: Mode,
        stage: StageSummary,
        started: float,
        reference: dict[str, Any] | None,
        perturbations: list[str] | None,
        intent_reference: dict[str, Any] | None,
        formal_properties: list[str] | None,
    ) -> ValidateResponse:
```

- [ ] **Step 4: Thread `parse_result.element_summary` through pipeline calls**

Add `elements=parse_result.element_summary` to every `_finish()` call in `validate()`.

Change the rules call:

```python
        violations = evaluate_rules(text, parse_result.element_summary, self.settings)
```

Change the veto call:

```python
        veto = evaluate_veto(
            text=text,
            elements=elements,
            settings=self.settings,
            semantic_path_passed=semantic_path_passed,
            parser_agreement=stage.parse.parser_agreement,
            violations=stage.constraint.violations if stage.constraint.reached else [],
        )
```

Change structural matching:

```python
            structural = match_structural(
                elements,
                reference,
                self.settings,
                soft_matcher=self.structural_matcher,
            )
```

- [ ] **Step 5: Migrate direct rules/veto tests**

In `tests/test_rules_veto_reward.py`, change imports:

```python
from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter, extract_element_summary
from syvern.models import ElementSummary, ...
```

Add helpers:

```python
def _elements(text: str):
    return extract_element_summary(text)


def _evaluate_rules(text: str, settings: SyvernSettings | None = None):
    resolved_settings = settings or SyvernSettings()
    return evaluate_rules(text, _elements(text), resolved_settings)
```

Replace direct calls like:

```python
violations = evaluate_rules("filler filler filler", SyvernSettings())
```

with:

```python
violations = _evaluate_rules("filler filler filler", SyvernSettings())
```

Update each direct `evaluate_veto()` call to pass `elements=_elements(text)`.

- [ ] **Step 6: Add focused unit assertions**

Add to `tests/test_rules_veto_reward.py`:

```python
def test_rules_use_supplied_elements_for_minimum_element_signal():
    violations = evaluate_rules(
        "plain words enough tokens",
        [ElementSummary(type="part", qualified_name="vehicle.engine")],
        SyvernSettings(),
    )

    assert "minimum_element_signal" not in {violation.rule for violation in violations}


def test_veto_uses_supplied_elements_for_degenerate_element_check():
    veto = evaluate_veto(
        text="plain words enough tokens",
        elements=[ElementSummary(type="part", qualified_name="vehicle.engine")],
        settings=SyvernSettings(),
        semantic_path_passed=True,
        parser_agreement=True,
        violations=[],
    )

    assert veto.triggered is False
```

- [ ] **Step 7: Run focused tests**

Run: `python -m pytest tests/test_rules_veto_reward.py tests/test_element_set_wiring.py::test_pipeline_consumes_adapter_elements_for_rules_veto_and_structural -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/syvern/pipeline.py src/syvern/rules.py src/syvern/veto.py tests/test_rules_veto_reward.py tests/test_element_set_wiring.py
git commit -m "refactor: thread parser element summaries through pipeline"
```

## Task 3: Make IPT Consume Pre-Parsed Element Sets

**Files:**
- Modify: `src/syvern/ipt.py`
- Modify: `src/syvern/pipeline.py`
- Modify: `tests/test_ipt.py`
- Modify: `tests/test_element_set_wiring.py`

- [ ] **Step 1: Rewrite `ipt.py` around element sets**

Replace `src/syvern/ipt.py` with:

```python
from __future__ import annotations

from syvern.models import ElementSummary
from syvern.settings import SyvernSettings
from syvern.structural import match_structural


def _reference_from_original_elements(
    original_elements: list[ElementSummary],
) -> dict[str, list[dict[str, str]]] | None:
    if not original_elements:
        return None
    return {
        "elements": [
            {"type": element.type, "qualified_name": element.qualified_name}
            for element in original_elements
        ]
    }


def evaluate_ipt(
    *,
    original_elements: list[ElementSummary],
    perturbation_element_sets: list[list[ElementSummary]] | None,
    settings: SyvernSettings,
) -> bool | None:
    reference = _reference_from_original_elements(original_elements)
    if not perturbation_element_sets or reference is None:
        return None

    for perturbation_elements in perturbation_element_sets:
        summary = match_structural(
            perturbation_elements,
            reference,
            settings,
        )
        if summary.f1 < settings.ipt_threshold:
            return False
    return True
```

- [ ] **Step 2: Update pipeline IPT call**

Add helper method to `ValidationPipeline`:

```python
    def _elements(self, text: str) -> list[ElementSummary]:
        return self.pilot.parse(text).element_summary
```

Change the IPT block in `_finish()`:

```python
        if ipt_evaluated:
            robustness = RobustnessSummary(
                ipt_consistent=evaluate_ipt(
                    original_elements=elements,
                    perturbation_element_sets=[
                        self._elements(perturbation) for perturbation in perturbations
                    ],
                    settings=self.settings,
                )
            )
```

- [ ] **Step 3: Update `tests/test_ipt.py` fixtures and calls**

Use this helper and fixtures:

```python
from syvern.ipt import evaluate_ipt
from syvern.models import ElementSummary
from syvern.settings import SyvernSettings


def _elements(*items: tuple[str, str]) -> list[ElementSummary]:
    return [
        ElementSummary(type=element_type, qualified_name=qualified_name)
        for element_type, qualified_name in items
    ]


ORIGINAL = _elements(
    ("part", "vehicle.engine"),
    ("attribute", "vehicle.mass"),
)

EQUIVALENT = _elements(
    ("attribute", "vehicle.mass"),
    ("part", "vehicle.engine"),
)
```

Convert each `evaluate_ipt(original_text=..., perturbations=...)` call to:

```python
evaluate_ipt(
    original_elements=ORIGINAL,
    perturbation_element_sets=[EQUIVALENT],
    settings=SyvernSettings(),
)
```

For empty/missing cases, assert:

```python
assert evaluate_ipt(
    original_elements=ORIGINAL,
    perturbation_element_sets=None,
    settings=SyvernSettings(),
) is None
assert evaluate_ipt(
    original_elements=[],
    perturbation_element_sets=[ORIGINAL],
    settings=SyvernSettings(),
) is None
assert evaluate_ipt(
    original_elements=_elements(("part", "vehicle.engine")),
    perturbation_element_sets=[[]],
    settings=SyvernSettings(),
) is False
```

- [ ] **Step 4: Add IPT integration coverage**

Add to `tests/test_element_set_wiring.py`:

```python
def test_pipeline_parses_ipt_perturbations_with_pilot_adapter():
    pilot = FakeElementAdapter()

    response = ValidationPipeline(
        pilot_adapter=pilot,
        monticore_adapter=AgreeingMontiCoreAdapter(),
    ).validate(
        "plain original words",
        mode="full",
        perturbations=["plain equivalent perturbation"],
    )

    assert response.robustness.ipt_consistent is True
    assert pilot.parse_calls == ["plain original words", "plain equivalent perturbation"]
```

- [ ] **Step 5: Run focused IPT tests**

Run: `python -m pytest tests/test_ipt.py tests/test_pipeline.py tests/test_element_set_wiring.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/syvern/ipt.py src/syvern/pipeline.py tests/test_ipt.py tests/test_element_set_wiring.py
git commit -m "refactor: evaluate ipt from parser element sets"
```

## Task 4: Add Red-Line And Import-Guard Coverage

**Files:**
- Modify: `tests/test_element_set_wiring.py`

- [ ] **Step 1: Add legal-vs-broken score regression**

Append:

```python
def test_broken_model_scores_below_valid_with_syntax_aware_adapter():
    pipeline = ValidationPipeline(
        pilot_adapter=FakeElementAdapter(),
        monticore_adapter=AgreeingMontiCoreAdapter(),
    )

    valid = pipeline.validate(
        "part def Vehicle { attribute mass : Real; part engine : Engine; }",
        mode="online_reward",
    )
    broken = pipeline.validate(
        "broken part def Vehicle { attribute mass : ;",
        mode="online_reward",
    )

    assert valid.stage.parse.ok is True
    assert broken.stage.parse.ok is False
    assert valid.meta.reward > broken.meta.reward
```

- [ ] **Step 2: Add business import guard**

Append:

```python
from pathlib import Path


def test_stub_element_extractor_is_not_imported_by_business_modules():
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in (root / "src" / "syvern").rglob("*.py"):
        if path.name == "stub.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "extract_element_summary" in text:
            offenders.append(path.relative_to(root).as_posix())

    assert offenders == []
```

- [ ] **Step 3: Run wiring tests**

Run: `python -m pytest tests/test_element_set_wiring.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_element_set_wiring.py
git commit -m "test: cover element summary source of truth"
```

## Task 5: Verification And Documentation

**Files:**
- Optionally modify: `README.md`
- Optionally modify: `STATUS.md`

- [ ] **Step 1: Verify no business module imports the stub extractor**

Run: `rg "extract_element_summary" src/syvern tests -g "*.py"`

Expected source matches only in:

```text
src/syvern/adapters/stub.py
```

Test matches in `tests/test_structural.py`, `tests/test_rules_veto_reward.py`, and `tests/test_element_summary.py` are acceptable.

- [ ] **Step 2: Run full tests**

Run: `python -m pytest -q -p no:cacheprovider`

Expected: all tests PASS.

- [ ] **Step 3: Run static checks**

Run: `python -m ruff check src tests`

Expected: PASS.

Run: `python -m mypy src`

Expected: PASS.

If either tool is missing, install CI extras and rerun:

```powershell
python -m pip install -e ".[ci]"
```

- [ ] **Step 4: Run diff whitespace check**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Optional docs update**

If updating `README.md` or `STATUS.md`, add:

```markdown
Parser-produced `ParseResult.element_summary` is threaded through rules, veto, structural matching, and IPT; the stub regex extractor remains confined to the stub adapter and tests.
```

- [ ] **Step 6: Commit docs if changed**

```bash
git add README.md STATUS.md
git commit -m "docs: note element set wiring status"
```

Skip this commit if no documentation files changed.

## Self-Review Checklist

- [ ] The main text is parsed once, and `_finish()` receives `parse_result.element_summary`.
- [ ] `pipeline.py`, `rules.py`, `veto.py`, and `ipt.py` no longer import `extract_element_summary`.
- [ ] `evaluate_rules()` and `evaluate_veto()` still use raw `text` for text-only checks.
- [ ] `match_structural()` signature remains unchanged.
- [ ] IPT perturbations are parsed independently through `self.pilot.parse()`.
- [ ] Stub behavior remains equivalent because `PilotStubAdapter.parse()` still uses the same regex internally.
- [ ] New fake-adapter tests prove downstream consumers trust adapter element sets.
- [ ] Full pytest, ruff, mypy, and `git diff --check` have passed or have documented skip reasons.
