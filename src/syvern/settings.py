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
    validator_fingerprint: str = "syvern-h1-stub@0.1.0+rules@h1"
    matching_policy_id: str = "h3-frozen-exact-v1"
    min_tokens: int = 3
    min_elements: int = 1
    repetition_ratio: float = 0.65
    cap_type: int = 4
    cap_cons: int = 4
    cap_hall: int = 4
    r_max: float = 1.0
    weights: RewardWeights = RewardWeights()

    def __post_init__(self) -> None:
        if not self.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
