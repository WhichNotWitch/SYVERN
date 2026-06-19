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

    parse_passed = s.parse.reached and s.parse.ok and s.parse.parser_agreement is not False
    resolve_passed = parse_passed and s.resolve.reached and s.resolve.ok
    typecheck_reached = resolve_passed and s.typecheck.reached
    constraint_reached = resolve_passed and s.constraint.reached
    t0_passed = (
        parse_passed
        and resolve_passed
        and s.typecheck.reached
        and s.typecheck.ok
        and s.constraint.reached
        and s.constraint.ok
    )

    reward = 0.0
    reward += w.w0 * (1 if parse_passed else 0)
    reward += w.w1 * (1 if resolve_passed else 0)
    reward += w.w2 * (1 - norm(s.typecheck.type_errors, settings.cap_type) if typecheck_reached else 0)
    reward += w.w3 * (1 - norm(_constraint_weight(s.constraint.violations), settings.cap_cons) if constraint_reached else 0)
    reward += (w.w4 * st.f1) if t0_passed else 0
    reward += (w.w5 * st.requirement_coverage) if t0_passed else 0
    reward += w.w6 * (1 if t0_passed and response.robustness.ipt_consistent else 0)
    reward -= w.w7 * norm(st.hallucinated_elements, settings.cap_hall)

    return max(0.0, min(settings.r_max, reward))
