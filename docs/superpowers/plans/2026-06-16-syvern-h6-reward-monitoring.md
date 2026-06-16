# SYVERN H6 Reward Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the H6 local reward operations and monitoring harness: request metadata, validation event recording, monitor summaries, divergence alerts, reward config visibility, online-reward smoke coverage, and README documentation.

**Architecture:** Keep H6 local and deterministic. Add focused pure modules for reward operations, validation records, and monitoring; keep API changes as thin wiring around the existing cache and pipeline. Metadata is accepted at the API request boundary, stored with validation events, and excluded from validation cache identity.

**Tech Stack:** Python, FastAPI, Pydantic, dataclasses, pytest, existing SYVERN pipeline/cache/reward modules.

---

## File Structure

- Create `src/syvern/reward_ops.py`: pure helpers that summarize and validate reward configuration from `SyvernSettings`.
- Create `src/syvern/records.py`: immutable validation event representation, response-to-record conversion, and in-memory record store.
- Create `src/syvern/monitoring.py`: aggregate monitor summaries and divergence alert helpers.
- Modify `src/syvern/settings.py`: H6 fingerprint plus monitor threshold settings.
- Modify `src/syvern/models.py`: optional request metadata and response models for reward configuration and monitor summaries.
- Modify `src/syvern/api.py`: module-level record store, validation recording, and read-only operations endpoints.
- Add `tests/test_reward_ops.py`: reward config summary and validation coverage.
- Add `tests/test_records.py`: record conversion and in-memory store coverage.
- Add `tests/test_monitoring.py`: aggregate and divergence coverage.
- Modify `tests/test_api.py`: API metadata, recording, cache event, and new endpoint coverage.
- Add `tests/test_online_reward_smoke.py`: conservative local online-reward throughput smoke test.
- Modify `README.md`: H6 operations, endpoints, monitoring semantics, and local-only limits.

## Task 1: Reward Config Models And Helpers

**Files:**
- Modify: `src/syvern/settings.py`
- Modify: `src/syvern/models.py`
- Create: `src/syvern/reward_ops.py`
- Create: `tests/test_reward_ops.py`

- [ ] **Step 1: Write failing tests for reward config summary and settings validation**

Create `tests/test_reward_ops.py`:

```python
import pytest

from syvern.reward_ops import reward_config_summary, validate_reward_settings
from syvern.settings import RewardWeights, SyvernSettings


def test_reward_config_summary_exposes_weights_caps_and_fingerprint():
    settings = SyvernSettings()

    summary = reward_config_summary(settings)

    assert summary.validator_fingerprint == settings.validator_fingerprint
    assert summary.weights == {
        "w0": settings.weights.w0,
        "w1": settings.weights.w1,
        "w2": settings.weights.w2,
        "w3": settings.weights.w3,
        "w4": settings.weights.w4,
        "w5": settings.weights.w5,
        "w6": settings.weights.w6,
        "w7": settings.weights.w7,
    }
    assert summary.caps == {
        "cap_type": settings.cap_type,
        "cap_cons": settings.cap_cons,
        "cap_hall": settings.cap_hall,
    }
    assert summary.r_max == settings.r_max
    assert summary.matching_policy_id == settings.matching_policy_id
    assert summary.judge_model == settings.judge_model
    assert summary.rubric_version == settings.rubric_version
    assert summary.ipt_threshold == settings.ipt_threshold


def test_validate_reward_settings_accepts_default_h6_settings():
    validate_reward_settings(SyvernSettings())


def test_validate_reward_settings_rejects_invalid_caps():
    settings = SyvernSettings(cap_type=0)

    with pytest.raises(ValueError, match="cap_type must be positive"):
        validate_reward_settings(settings)


def test_validate_reward_settings_rejects_invalid_r_max():
    settings = SyvernSettings(r_max=0.0)

    with pytest.raises(ValueError, match="r_max must be positive"):
        validate_reward_settings(settings)


def test_validate_reward_settings_rejects_missing_identifier():
    settings = SyvernSettings(matching_policy_id=" ")

    with pytest.raises(ValueError, match="matching_policy_id must not be empty"):
        validate_reward_settings(settings)


def test_validate_reward_settings_rejects_incomplete_weights():
    class PartialWeights:
        w0 = 0.25
        w1 = 0.25
        w2 = 0.20
        w3 = 0.20
        w4 = 0.05
        w5 = 0.05
        w6 = 0.00

    settings = SyvernSettings(weights=RewardWeights())
    object.__setattr__(settings, "weights", PartialWeights())

    with pytest.raises(ValueError, match="missing reward weight w7"):
        validate_reward_settings(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reward_ops.py -q -p no:cacheprovider`

Expected: FAIL with `ModuleNotFoundError: No module named 'syvern.reward_ops'`.

- [ ] **Step 3: Add H6 settings, request metadata, and response models**

Modify `src/syvern/settings.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RewardWeights:
    w0: float = 0.25
    w1: float = 0.25
    w2: float = 0.20
    w3: float = 0.20
    w4: float = 0.05
    w5: float = 0.05
    w6: float = 0.00
    w7: float = 0.10


@dataclass(frozen=True)
class SyvernSettings:
    validator_fingerprint: str = "syvern-h6-stub@0.6.0+rules@h4+judge@h5+ops@h6"
    matching_policy_id: str = "h3-frozen-exact-v1"
    judge_model: str = "h5-deterministic-judge"
    rubric_version: str = "h5-rubric-v1"
    intent_vote_count: int = 3
    kappa_min: float = 0.6
    min_tokens: int = 3
    min_elements: int = 1
    repetition_ratio: float = 0.65
    enum_ratio: float = 0.75
    enum_min_group_size: int = 4
    ipt_threshold: float = 1.0
    cap_type: int = 4
    cap_cons: int = 4
    cap_hall: int = 4
    r_max: float = 1.0
    monitor_semantic_gain_threshold: float = 0.20
    monitor_coverage_stall_threshold: float = 0.05
    monitor_veto_rate_increase_threshold: float = 0.20
    monitor_stable_drop_threshold: float = 0.20
    weights: RewardWeights = RewardWeights()

    def __post_init__(self) -> None:
        if not self.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
        if not self.judge_model.strip():
            raise ValueError("judge_model must not be empty")
        if not self.rubric_version.strip():
            raise ValueError("rubric_version must not be empty")
        if self.intent_vote_count < 1:
            raise ValueError("intent_vote_count must be at least 1")
        if not -1.0 <= self.kappa_min <= 1.0:
            raise ValueError("kappa_min must be between -1.0 and 1.0")
```

Modify the top request and operations-model area of `src/syvern/models.py`:

```python
class ValidateRequest(BaseModel):
    text: str
    reference: dict[str, Any] | None = None
    perturbations: list[str] | None = None
    intent_reference: dict[str, Any] | None = None
    metadata: dict[str, str] | None = None
    mode: Mode = "online_reward"
    k: int | None = Field(default=None, ge=1)


class BatchValidateRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    reference: dict[str, Any] | None = None
    perturbations: list[str] | None = None
    intent_reference: dict[str, Any] | None = None
    metadata: dict[str, str] | None = None
    mode: Mode = "online_reward"
```

Add these models near the existing summary models in `src/syvern/models.py`:

```python
class DivergenceAlert(BaseModel):
    code: str
    message: str
    severity: Severity


class RewardConfigSummary(BaseModel):
    validator_fingerprint: str
    weights: dict[str, float]
    caps: dict[str, int]
    r_max: float
    matching_policy_id: str
    judge_model: str
    rubric_version: str
    ipt_threshold: float


class MonitorAggregateSummary(BaseModel):
    record_count: int = Field(ge=0)
    semantic_pass_rate: float = Field(ge=0.0, le=1.0)
    t0_pass_rate: float = Field(ge=0.0, le=1.0)
    t1_available_rate: float = Field(ge=0.0, le=1.0)
    veto_rate: float = Field(ge=0.0, le=1.0)
    average_requirement_coverage: float = Field(ge=0.0, le=1.0)
    average_reward: float
    average_latency_ms: float = Field(ge=0.0)
    stable_at_k: float = Field(ge=0.0, le=1.0)
    divergence_alerts: list[DivergenceAlert] = Field(default_factory=list)
```

- [ ] **Step 4: Implement reward operations helpers**

Create `src/syvern/reward_ops.py`:

```python
from __future__ import annotations

from syvern.models import RewardConfigSummary
from syvern.settings import SyvernSettings


WEIGHT_NAMES = ("w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7")


def reward_config_summary(settings: SyvernSettings) -> RewardConfigSummary:
    validate_reward_settings(settings)
    return RewardConfigSummary(
        validator_fingerprint=settings.validator_fingerprint,
        weights={name: float(getattr(settings.weights, name)) for name in WEIGHT_NAMES},
        caps={
            "cap_type": settings.cap_type,
            "cap_cons": settings.cap_cons,
            "cap_hall": settings.cap_hall,
        },
        r_max=settings.r_max,
        matching_policy_id=settings.matching_policy_id,
        judge_model=settings.judge_model,
        rubric_version=settings.rubric_version,
        ipt_threshold=settings.ipt_threshold,
    )


def validate_reward_settings(settings: SyvernSettings) -> None:
    if not settings.validator_fingerprint.strip():
        raise ValueError("validator_fingerprint must not be empty")
    if not settings.matching_policy_id.strip():
        raise ValueError("matching_policy_id must not be empty")
    for name in WEIGHT_NAMES:
        if not hasattr(settings.weights, name):
            raise ValueError(f"missing reward weight {name}")
    for name in ("cap_type", "cap_cons", "cap_hall"):
        if getattr(settings, name) <= 0:
            raise ValueError(f"{name} must be positive")
    if settings.r_max <= 0:
        raise ValueError("r_max must be positive")
```

- [ ] **Step 5: Run reward operations tests**

Run: `python -m pytest tests/test_reward_ops.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/syvern/settings.py src/syvern/models.py src/syvern/reward_ops.py tests/test_reward_ops.py
git commit -m "feat: add h6 reward config helpers"
```

## Task 2: Validation Record Store

**Files:**
- Create: `src/syvern/records.py`
- Create: `tests/test_records.py`

- [ ] **Step 1: Write failing tests for record conversion and store isolation**

Create `tests/test_records.py`:

```python
from syvern.pipeline import ValidationPipeline
from syvern.records import InMemoryValidationRecordStore, make_validation_record


def test_make_validation_record_extracts_h6_fields():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")
    response.meta.cache_hit = True

    record = make_validation_record(response, metadata={"domain": "vehicle"})

    assert record.sample_id == response.sample_id
    assert record.text_hash == response.meta.text_hash
    assert record.mode == "online_reward"
    assert record.validator_fingerprint == response.meta.validator_fingerprint
    assert record.cache_hit is True
    assert record.semantic_pass is True
    assert record.t0_pass is True
    assert record.t1_available is False
    assert record.veto_triggered is False
    assert record.veto_reason is None
    assert record.requirement_coverage == 0.0
    assert record.stable_at_k is None
    assert record.reward == response.meta.reward
    assert record.latency_ms == response.meta.latency_ms
    assert record.metadata == {"domain": "vehicle"}


def test_make_validation_record_defaults_missing_metadata_to_empty_dict():
    response = ValidationPipeline().validate("part A attribute x", mode="online_reward")

    record = make_validation_record(response, metadata=None)

    assert record.metadata == {}


def test_record_store_records_and_clears_events_in_order():
    store = InMemoryValidationRecordStore()
    first = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={"n": "1"})
    second = make_validation_record(ValidationPipeline().validate("part B unresolved_ref"), metadata={"n": "2"})

    store.add(first)
    store.add(second)

    assert store.list() == [first, second]
    store.clear()
    assert store.list() == []


def test_record_store_returns_copy_of_records_list():
    store = InMemoryValidationRecordStore()
    record = make_validation_record(ValidationPipeline().validate("part A attribute x"), metadata={})
    store.add(record)

    listed = store.list()
    listed.clear()

    assert store.list() == [record]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_records.py -q -p no:cacheprovider`

Expected: FAIL with `ModuleNotFoundError: No module named 'syvern.records'`.

- [ ] **Step 3: Implement records module**

Create `src/syvern/records.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from syvern.models import Mode, ValidateResponse
from syvern.robustness import semantic_pass


@dataclass(frozen=True)
class ValidationRecord:
    sample_id: str
    text_hash: str
    mode: Mode
    validator_fingerprint: str
    cache_hit: bool
    semantic_pass: bool
    t0_pass: bool
    t1_available: bool
    veto_triggered: bool
    veto_reason: str | None
    requirement_coverage: float
    stable_at_k: float | None
    reward: float
    latency_ms: int
    metadata: dict[str, str]


class InMemoryValidationRecordStore:
    def __init__(self) -> None:
        self._records: list[ValidationRecord] = []

    def add(self, record: ValidationRecord) -> None:
        self._records.append(record)

    def list(self) -> list[ValidationRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()


def make_validation_record(
    response: ValidateResponse,
    *,
    metadata: dict[str, str] | None,
) -> ValidationRecord:
    return ValidationRecord(
        sample_id=response.sample_id,
        text_hash=response.meta.text_hash,
        mode=response.meta.mode,
        validator_fingerprint=response.meta.validator_fingerprint,
        cache_hit=response.meta.cache_hit,
        semantic_pass=semantic_pass(response),
        t0_pass=response.tier_summary.t0_pass,
        t1_available=response.tier_summary.t1_available,
        veto_triggered=response.veto.triggered,
        veto_reason=response.veto.reason,
        requirement_coverage=response.structural.requirement_coverage if response.structural.evaluated else 0.0,
        stable_at_k=response.robustness.stable_at_k,
        reward=response.meta.reward,
        latency_ms=response.meta.latency_ms,
        metadata=dict(metadata or {}),
    )
```

- [ ] **Step 4: Run record tests**

Run: `python -m pytest tests/test_records.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/syvern/records.py tests/test_records.py
git commit -m "feat: record h6 validation events"
```

## Task 3: Monitor Aggregates And Divergence Alerts

**Files:**
- Create: `src/syvern/monitoring.py`
- Create: `tests/test_monitoring.py`

- [ ] **Step 1: Write failing monitor aggregation and divergence tests**

Create `tests/test_monitoring.py`:

```python
from syvern.models import Mode
from syvern.monitoring import aggregate_monitor_summary, detect_divergence
from syvern.records import ValidationRecord
from syvern.settings import SyvernSettings


def _record(
    *,
    semantic_pass: bool = True,
    t0_pass: bool = True,
    t1_available: bool = False,
    veto_triggered: bool = False,
    requirement_coverage: float = 0.0,
    reward: float = 0.5,
    latency_ms: int = 4,
) -> ValidationRecord:
    return ValidationRecord(
        sample_id="sample",
        text_hash="hash",
        mode="online_reward",
        validator_fingerprint="fingerprint",
        cache_hit=False,
        semantic_pass=semantic_pass,
        t0_pass=t0_pass,
        t1_available=t1_available,
        veto_triggered=veto_triggered,
        veto_reason="forced" if veto_triggered else None,
        requirement_coverage=requirement_coverage,
        stable_at_k=None,
        reward=reward,
        latency_ms=latency_ms,
        metadata={},
    )


def test_empty_monitor_summary_returns_zero_rates_and_no_alerts():
    summary = aggregate_monitor_summary([])

    assert summary.record_count == 0
    assert summary.semantic_pass_rate == 0.0
    assert summary.t0_pass_rate == 0.0
    assert summary.t1_available_rate == 0.0
    assert summary.veto_rate == 0.0
    assert summary.average_requirement_coverage == 0.0
    assert summary.average_reward == 0.0
    assert summary.average_latency_ms == 0.0
    assert summary.stable_at_k == 0.0
    assert summary.divergence_alerts == []


def test_monitor_summary_computes_rates_and_averages():
    summary = aggregate_monitor_summary(
        [
            _record(requirement_coverage=1.0, reward=1.0, latency_ms=10, t1_available=True),
            _record(semantic_pass=False, t0_pass=False, veto_triggered=True, reward=0.0, latency_ms=20),
        ]
    )

    assert summary.record_count == 2
    assert summary.semantic_pass_rate == 0.5
    assert summary.t0_pass_rate == 0.5
    assert summary.t1_available_rate == 0.5
    assert summary.veto_rate == 0.5
    assert summary.average_requirement_coverage == 0.5
    assert summary.average_reward == 0.5
    assert summary.average_latency_ms == 15.0
    assert summary.stable_at_k == 0.5
    assert summary.divergence_alerts == []


def test_divergence_flags_semantic_gain_without_coverage_gain():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary(
        [_record(semantic_pass=False, t0_pass=False, requirement_coverage=0.2) for _ in range(5)]
    )
    current = aggregate_monitor_summary(
        [_record(semantic_pass=True, t0_pass=True, requirement_coverage=0.22) for _ in range(5)]
    )

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["semantic_without_coverage"]
    assert alerts[0].severity == "warn"


def test_divergence_flags_veto_rate_increase():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary([_record(veto_triggered=False) for _ in range(5)])
    current = aggregate_monitor_summary([_record(veto_triggered=True) for _ in range(5)])

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["veto_rate_increase"]


def test_divergence_flags_stable_at_k_drop():
    settings = SyvernSettings()
    previous = aggregate_monitor_summary([_record(semantic_pass=True) for _ in range(5)])
    current = aggregate_monitor_summary([_record(semantic_pass=False, t0_pass=False) for _ in range(5)])

    alerts = detect_divergence(previous, current, settings)

    assert [alert.code for alert in alerts] == ["stable_at_k_drop"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_monitoring.py -q -p no:cacheprovider`

Expected: FAIL with `ModuleNotFoundError: No module named 'syvern.monitoring'`.

- [ ] **Step 3: Implement monitoring module**

Create `src/syvern/monitoring.py`:

```python
from __future__ import annotations

from syvern.models import DivergenceAlert, MonitorAggregateSummary
from syvern.records import ValidationRecord
from syvern.settings import SyvernSettings


def _rate(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return count / total


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def aggregate_monitor_summary(records: list[ValidationRecord]) -> MonitorAggregateSummary:
    total = len(records)
    return MonitorAggregateSummary(
        record_count=total,
        semantic_pass_rate=_rate(sum(1 for record in records if record.semantic_pass), total),
        t0_pass_rate=_rate(sum(1 for record in records if record.t0_pass), total),
        t1_available_rate=_rate(sum(1 for record in records if record.t1_available), total),
        veto_rate=_rate(sum(1 for record in records if record.veto_triggered), total),
        average_requirement_coverage=_average([record.requirement_coverage for record in records]),
        average_reward=_average([record.reward for record in records]),
        average_latency_ms=_average([float(record.latency_ms) for record in records]),
        stable_at_k=_rate(sum(1 for record in records if record.semantic_pass), total),
        divergence_alerts=[],
    )


def detect_divergence(
    previous: MonitorAggregateSummary,
    current: MonitorAggregateSummary,
    settings: SyvernSettings,
) -> list[DivergenceAlert]:
    alerts: list[DivergenceAlert] = []
    semantic_gain = current.semantic_pass_rate - previous.semantic_pass_rate
    coverage_gain = current.average_requirement_coverage - previous.average_requirement_coverage
    veto_gain = current.veto_rate - previous.veto_rate
    stable_drop = previous.stable_at_k - current.stable_at_k

    if (
        semantic_gain >= settings.monitor_semantic_gain_threshold
        and coverage_gain <= settings.monitor_coverage_stall_threshold
    ):
        alerts.append(
            DivergenceAlert(
                code="semantic_without_coverage",
                message="semantic pass rate increased while requirement coverage stalled",
                severity="warn",
            )
        )
    if veto_gain >= settings.monitor_veto_rate_increase_threshold:
        alerts.append(
            DivergenceAlert(
                code="veto_rate_increase",
                message="veto rate increased beyond the H6 monitoring threshold",
                severity="warn",
            )
        )
    if stable_drop >= settings.monitor_stable_drop_threshold:
        alerts.append(
            DivergenceAlert(
                code="stable_at_k_drop",
                message="stable_at_k dropped beyond the H6 monitoring threshold",
                severity="warn",
            )
        )
    return alerts
```

- [ ] **Step 4: Run monitor tests**

Run: `python -m pytest tests/test_monitoring.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/syvern/monitoring.py tests/test_monitoring.py
git commit -m "feat: add h6 monitor summaries"
```

## Task 4: API Recording And Operations Endpoints

**Files:**
- Modify: `src/syvern/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing API tests for metadata, recording, cache events, and endpoints**

Modify `tests/test_api.py` imports:

```python
from syvern.api import app, validation_cache, validation_records
```

Modify `setup_function`:

```python
def setup_function():
    validation_cache.clear()
    validation_records.clear()
```

Add tests to `tests/test_api.py`:

```python
def test_validate_accepts_metadata_records_event_without_echoing_metadata():
    client = TestClient(app)
    payload = {
        "text": "part A attribute x",
        "mode": "online_reward",
        "metadata": {"domain": "vehicle", "checkpoint": "rft-001"},
    }

    response = client.post("/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "metadata" not in body
    records = validation_records.list()
    assert len(records) == 1
    assert records[0].metadata == {"domain": "vehicle", "checkpoint": "rft-001"}
    assert records[0].cache_hit is False


def test_validate_rejects_non_string_metadata_value():
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"epoch": 1}},
    )

    assert response.status_code == 422


def test_metadata_does_not_change_cache_identity_but_records_each_event():
    client = TestClient(app)
    first = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"checkpoint": "a"}},
    ).json()
    second = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"checkpoint": "b"}},
    ).json()

    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    records = validation_records.list()
    assert [record.metadata for record in records] == [{"checkpoint": "a"}, {"checkpoint": "b"}]
    assert [record.cache_hit for record in records] == [False, True]


def test_validate_batch_records_every_item_in_order_with_metadata():
    client = TestClient(app)
    payload = {
        "texts": ["part A attribute x", "part B unresolved_ref"],
        "mode": "online_reward",
        "metadata": {"domain": "vehicle"},
    }

    response = client.post("/validate_batch", json=payload)

    assert response.status_code == 200
    records = validation_records.list()
    assert len(records) == 2
    assert [record.text_hash for record in records] == [
        item["meta"]["text_hash"] for item in response.json()["responses"]
    ]
    assert [record.metadata for record in records] == [{"domain": "vehicle"}, {"domain": "vehicle"}]


def test_reward_config_endpoint_returns_h6_config():
    client = TestClient(app)

    response = client.get("/reward_config")

    assert response.status_code == 200
    body = response.json()
    assert body["validator_fingerprint"].startswith("syvern-h6-stub@0.6.0")
    assert set(body["weights"]) == {"w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7"}
    assert body["caps"] == {"cap_type": 4, "cap_cons": 4, "cap_hall": 4}
    assert body["matching_policy_id"] == "h3-frozen-exact-v1"


def test_monitor_summary_endpoint_returns_empty_then_recorded_summary():
    client = TestClient(app)

    empty = client.get("/monitor_summary").json()
    assert empty["record_count"] == 0
    assert empty["semantic_pass_rate"] == 0.0
    assert empty["divergence_alerts"] == []

    client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"})
    current = client.get("/monitor_summary").json()

    assert current["record_count"] == 1
    assert current["semantic_pass_rate"] == 1.0
    assert current["t0_pass_rate"] == 1.0
    assert current["stable_at_k"] == 1.0
```

- [ ] **Step 2: Run focused API tests to verify they fail**

Run: `python -m pytest tests/test_api.py -q -p no:cacheprovider`

Expected: FAIL with import error for `validation_records` or 404 for new endpoints.

- [ ] **Step 3: Wire recording and endpoints into API**

Modify `src/syvern/api.py` imports:

```python
from syvern.monitoring import aggregate_monitor_summary
from syvern.records import InMemoryValidationRecordStore, make_validation_record
from syvern.reward_ops import reward_config_summary
```

Add response models to the existing models import:

```python
    MonitorAggregateSummary,
    RewardConfigSummary,
```

Add module-level store:

```python
validation_records = InMemoryValidationRecordStore()
```

Modify `_validate_with_cache` signature:

```python
def _validate_with_cache(
    text: str,
    *,
    mode: Mode,
    reference: dict | None,
    perturbations: list[str] | None,
    intent_reference: dict | None,
    metadata: dict[str, str] | None,
) -> ValidateResponse:
```

Modify the cached branch:

```python
    cached = validation_cache.get(key)
    if cached is not None:
        cached_payload = deepcopy(cached)
        cached_payload["meta"]["cache_hit"] = True
        response = ValidateResponse.model_validate(cached_payload)
        validation_records.add(make_validation_record(response, metadata=metadata))
        return response
```

Modify the non-cached return path:

```python
    validation_cache.set(key, payload)
    validated = ValidateResponse.model_validate(payload)
    validation_records.add(make_validation_record(validated, metadata=metadata))
    return validated
```

Pass metadata from `/validate`:

```python
        metadata=request.metadata,
```

Pass metadata from `/validate_batch`:

```python
            metadata=request.metadata,
```

Add endpoints:

```python
@app.get("/reward_config", response_model=RewardConfigSummary)
def reward_config() -> RewardConfigSummary:
    return reward_config_summary(settings)


@app.get("/monitor_summary", response_model=MonitorAggregateSummary)
def monitor_summary() -> MonitorAggregateSummary:
    return aggregate_monitor_summary(validation_records.list())
```

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_api.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/syvern/api.py tests/test_api.py
git commit -m "feat: expose h6 monitoring endpoints"
```

## Task 5: Throughput Smoke, README, And Full Verification

**Files:**
- Create: `tests/test_online_reward_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Write online-reward throughput smoke test**

Create `tests/test_online_reward_smoke.py`:

```python
from time import perf_counter

from syvern.pipeline import ValidationPipeline


def test_online_reward_local_stub_throughput_smoke():
    pipeline = ValidationPipeline()
    samples = [
        "part A attribute x",
        "part B unresolved_ref",
        "part C type_error",
        "part D attribute y",
        "part E attribute z",
    ]

    started = perf_counter()
    responses = [pipeline.validate(sample, mode="online_reward") for sample in samples]
    elapsed = perf_counter() - started

    assert [response.intent.evaluated for response in responses] == [False, False, False, False, False]
    assert [response.structural.evaluated for response in responses] == [False, False, False, False, False]
    assert [response.robustness.ipt_consistent for response in responses] == [None, None, None, None, None]
    assert elapsed < 1.0
```

- [ ] **Step 2: Run throughput smoke**

Run: `python -m pytest tests/test_online_reward_smoke.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 3: Update README H6 sections**

Modify the opening paragraph in `README.md` to include H6:

```markdown
SYVERN is the SysML V2 Evaluation and Reward Engine. This repository currently implements the H1 T0 core, H2 deterministic robustness slice, H3 deterministic structural matching slice, H4 deterministic anti-gaming/IPT slice, H5 deterministic intent-judging/calibration harness, and H6 deterministic reward-readiness/monitoring harness from the design docs: a validation and reward service with `/validate`, `/validate_batch`, `/reward_config`, `/monitor_summary`, Stage 0-5 pipeline, cross-parser element-summary agreement in `full` mode, batch `pass@k` / `stable@k` metrics, reference-based structural `precision` / `recall` / `f1` / `requirement_coverage`, anti-gaming vetoes, caller-supplied IPT consistency, deterministic intent judging, Cohen's kappa calibration helpers, cache/fingerprint behavior, in-memory validation event recording, monitor summaries, reward configuration visibility, L1 rules, veto checks, and reward mapping.
```

Add this section after the H5 section:

```markdown
## H6 reward readiness and monitoring

H6 adds local operations visibility around the deterministic reward harness:

- `GET /reward_config` returns the current validator fingerprint, reward weights `w0..w7`, caps, `r_max`, matching policy, judge model, rubric version, and IPT threshold.
- `GET /monitor_summary` returns aggregate metrics over the in-memory validation event store: record count, semantic pass rate, T0 pass rate, T1 availability, veto rate, average requirement coverage, average reward, average latency, stable rate, and divergence alerts.
- `POST /validate` and `POST /validate_batch` accept optional string metadata such as `domain`, `difficulty`, and `checkpoint`. Metadata is recorded with validation events but is not returned in validation responses and is not part of cache identity.
- Cache hits are recorded as validation service events, so monitor summaries reflect service traffic rather than only fresh pipeline executions.
- The RL effective-range helper can flag `semantic_without_coverage`, `veto_rate_increase`, and `stable_at_k_drop` when aggregate windows drift beyond H6 thresholds.
- The `online_reward` smoke test checks that the local stub path remains fast and does not run full-mode-only structural, IPT, or intent work.

H6 storage is intentionally in memory. Records reset when the process restarts, and this repository still does not include a production database, dashboard, authentication, background jobs, external metrics, or real SysML backend benchmark.
```

Add endpoint examples near existing API examples:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/reward_config
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/monitor_summary
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/validate -ContentType "application/json" -Body '{"text":"part A attribute x","mode":"online_reward","metadata":{"domain":"vehicle","checkpoint":"rft-001"}}'
```

- [ ] **Step 4: Run README and H6 focused tests**

Run: `python -m pytest tests/test_reward_ops.py tests/test_records.py tests/test_monitoring.py tests/test_api.py tests/test_online_reward_smoke.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add README.md tests/test_online_reward_smoke.py
git commit -m "docs: document h6 reward monitoring"
```

- [ ] **Step 6: Run full verification**

Run: `python -m pytest -q -p no:cacheprovider`

Expected: all tests PASS.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 7: Request final code review**

Use `superpowers:requesting-code-review` after full verification. The review must check H6 spec coverage, API response compatibility, cache identity, metadata isolation, monitor math, divergence thresholds, reward config validation, README accuracy, and test coverage.
