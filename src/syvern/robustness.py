from __future__ import annotations

from dataclasses import dataclass

from syvern.models import ValidateResponse


@dataclass(frozen=True)
class RobustnessMetrics:
    pass_at_k: float
    stable_at_k: float


def semantic_pass(response: ValidateResponse) -> bool:
    stage = response.stage
    return (
        stage.parse.reached
        and stage.parse.ok
        and stage.resolve.reached
        and stage.resolve.ok
        and stage.typecheck.reached
        and stage.typecheck.ok
    )


def aggregate_robustness(responses: list[ValidateResponse]) -> RobustnessMetrics:
    if not responses:
        raise ValueError("responses must not be empty")
    passed = sum(1 for response in responses if semantic_pass(response))
    return RobustnessMetrics(
        pass_at_k=1.0 if passed else 0.0,
        stable_at_k=passed / len(responses),
    )
