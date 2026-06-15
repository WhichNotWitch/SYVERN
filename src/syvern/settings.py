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
    validator_fingerprint: str = "syvern-h5-stub@0.5.0+rules@h4+judge@h5"
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
