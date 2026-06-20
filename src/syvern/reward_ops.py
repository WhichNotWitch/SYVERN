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
        fuzzy_threshold=settings.fuzzy_threshold,
        judge_model=settings.judge_model,
        rubric_version=settings.rubric_version,
        ipt_threshold=settings.ipt_threshold,
        data_filter_min_reward=settings.data_filter_min_reward,
        data_filter_min_stage=settings.data_filter_min_stage,
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
    if settings.fuzzy_threshold < 0:
        raise ValueError("fuzzy_threshold must not be negative")
    if not 0.0 <= settings.data_filter_min_reward <= settings.r_max:
        raise ValueError("data_filter_min_reward must be between 0.0 and r_max")
