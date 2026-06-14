from __future__ import annotations

from syvern.models import ValidateResponse, Violation
from syvern.rules import weighted_violations
from syvern.settings import SyvernSettings


def norm(value: int | float, cap: int | float) -> float:
    if cap <= 0:
        return 1.0
    return min(float(value) / float(cap), 1.0)


def _constraint_weight(violations: list[Violation]) -> int:
    return weighted_violations(violations)


def compute_reward(response: ValidateResponse, settings: SyvernSettings) -> float:
    if response.veto.triggered:
        return 0.0

    s = response.stage
    st = response.structural
    w = settings.weights

    reward = 0.0
    reward += w.w0 * (1 if s.parse.ok and s.parse.parser_agreement else 0)
    reward += w.w1 * (1 if s.resolve.ok else 0)
    reward += w.w2 * (1 - norm(s.typecheck.type_errors, settings.cap_type))
    reward += w.w3 * (1 - norm(_constraint_weight(s.constraint.violations), settings.cap_cons))
    reward += w.w4 * st.f1
    reward += w.w5 * st.requirement_coverage
    reward += w.w6 * (1 if response.robustness.ipt_consistent else 0)
    reward -= w.w7 * norm(st.hallucinated_elements, settings.cap_hall)

    return max(0.0, min(settings.r_max, reward))
