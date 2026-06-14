from __future__ import annotations

from collections import Counter
import re

from syvern.models import Violation
from syvern.normalization import normalize_ws
from syvern.settings import SyvernSettings


SEVERITY_WEIGHTS = {"warn": 1, "error": 2}


def evaluate_rules(text: str, settings: SyvernSettings) -> list[Violation]:
    normalized = normalize_ws(text).lower()
    violations: list[Violation] = []

    if re.search(r"\b(filler|dummy)\b", normalized) or "???" in normalized:
        violations.append(Violation(rule="no_filler_text", severity="error", category="anti_gaming"))

    words = normalized.split()
    if words:
        most_common = Counter(words).most_common(1)[0][1]
        if most_common / len(words) > settings.repetition_ratio and len(words) >= settings.min_tokens:
            violations.append(Violation(rule="no_excessive_repetition", severity="error", category="anti_gaming"))

    if 0 < len(words) < settings.min_tokens:
        violations.append(Violation(rule="minimum_model_signal", severity="warn", category="anti_gaming"))

    return violations


def weighted_violations(violations: list[Violation]) -> int:
    return sum(SEVERITY_WEIGHTS[v.severity] for v in violations)
