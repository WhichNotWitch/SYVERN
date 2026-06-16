from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from syvern.settings import SyvernSettings


@dataclass(frozen=True)
class CalibrationResult:
    kappa: float
    passed: bool


def _validate_labels(human_labels: Sequence[int], judge_labels: Sequence[int]) -> None:
    if len(human_labels) != len(judge_labels):
        raise ValueError("human_labels and judge_labels must have the same length")
    if not human_labels:
        raise ValueError("calibration labels must not be empty")
    for label in [*human_labels, *judge_labels]:
        if isinstance(label, bool) or not isinstance(label, int) or label < 0 or label > 5:
            raise ValueError("calibration labels must be integer buckets in 0..5")


def cohen_kappa(human_labels: Sequence[int], judge_labels: Sequence[int]) -> float:
    _validate_labels(human_labels, judge_labels)
    total = len(human_labels)
    observed = sum(1 for human, judge in zip(human_labels, judge_labels) if human == judge) / total

    human_counts = Counter(human_labels)
    judge_counts = Counter(judge_labels)
    expected = sum((human_counts[label] / total) * (judge_counts[label] / total) for label in range(6))

    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def evaluate_calibration(
    human_labels: Sequence[int],
    judge_labels: Sequence[int],
    settings: SyvernSettings,
) -> CalibrationResult:
    kappa = cohen_kappa(human_labels, judge_labels)
    return CalibrationResult(kappa=kappa, passed=kappa >= settings.kappa_min)
