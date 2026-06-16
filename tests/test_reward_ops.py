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
