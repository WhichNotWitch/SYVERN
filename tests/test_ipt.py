from syvern.ipt import evaluate_ipt
from syvern.settings import SyvernSettings


REFERENCE = {
    "elements": [
        {"type": "part", "qualified_name": "vehicle.engine"},
        {"type": "attribute", "qualified_name": "vehicle.mass"},
    ],
    "requirements": ["req.power", "req.mass"],
    "coverage": {
        "req.power": ["vehicle.engine"],
        "req.mass": ["vehicle.mass"],
    },
}


def test_equivalent_perturbations_are_ipt_consistent():
    result = evaluate_ipt(
        original_text="part vehicle.engine attribute vehicle.mass",
        perturbations=[
            "attribute vehicle.mass part vehicle.engine",
            "part vehicle.engine attribute vehicle.mass",
        ],
        settings=SyvernSettings(),
    )

    assert result is True


def test_structurally_different_perturbation_is_not_ipt_consistent():
    result = evaluate_ipt(
        original_text="part vehicle.engine attribute vehicle.mass",
        perturbations=[
            "part vehicle.engine attribute vehicle.mass",
            "part vehicle.engine",
        ],
        settings=SyvernSettings(),
    )

    assert result is False


def test_missing_or_empty_perturbations_are_unevaluated():
    assert evaluate_ipt(
        original_text="part vehicle.engine",
        perturbations=None,
        settings=SyvernSettings(),
    ) is None
    assert evaluate_ipt(
        original_text="part vehicle.engine",
        perturbations=[],
        settings=SyvernSettings(),
    ) is None


def test_missing_original_output_is_unevaluated_even_with_perturbations():
    assert evaluate_ipt(
        original_text="",
        perturbations=["part vehicle.engine"],
        settings=SyvernSettings(),
    ) is None


def test_blank_perturbation_is_inconsistent_when_ipt_is_eligible():
    assert evaluate_ipt(
        original_text="part vehicle.engine",
        perturbations=[""],
        settings=SyvernSettings(),
    ) is False


def test_ipt_compares_perturbed_outputs_to_original_output_not_external_reference():
    result = evaluate_ipt(
        original_text="part vehicle.engine attribute vehicle.mass",
        perturbations=["part vehicle.engine attribute vehicle.mass"],
        settings=SyvernSettings(),
    )

    assert result is True
