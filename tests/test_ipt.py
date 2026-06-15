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
        perturbations=[
            "attribute vehicle.mass part vehicle.engine",
            "part vehicle.engine attribute vehicle.mass",
        ],
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert result is True


def test_structurally_different_perturbation_is_not_ipt_consistent():
    result = evaluate_ipt(
        perturbations=[
            "part vehicle.engine attribute vehicle.mass",
            "part vehicle.engine",
        ],
        reference=REFERENCE,
        settings=SyvernSettings(),
    )

    assert result is False


def test_missing_or_empty_perturbations_are_unevaluated():
    assert evaluate_ipt(perturbations=None, reference=REFERENCE, settings=SyvernSettings()) is None
    assert evaluate_ipt(perturbations=[], reference=REFERENCE, settings=SyvernSettings()) is None


def test_blank_perturbation_is_inconsistent_when_ipt_is_eligible():
    assert evaluate_ipt(perturbations=[""], reference=REFERENCE, settings=SyvernSettings()) is False
