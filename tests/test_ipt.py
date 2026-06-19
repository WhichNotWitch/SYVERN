from syvern.models import ElementSummary
from syvern.ipt import evaluate_ipt
from syvern.settings import SyvernSettings


def _elements(*items: tuple[str, str]) -> list[ElementSummary]:
    return [
        ElementSummary(type=element_type, qualified_name=qualified_name)
        for element_type, qualified_name in items
    ]


ORIGINAL = _elements(
    ("part", "vehicle.engine"),
    ("attribute", "vehicle.mass"),
)
EQUIVALENT = _elements(
    ("attribute", "vehicle.mass"),
    ("part", "vehicle.engine"),
)


def test_equivalent_perturbations_are_ipt_consistent():
    result = evaluate_ipt(
        original_elements=ORIGINAL,
        perturbation_element_sets=[EQUIVALENT, ORIGINAL],
        settings=SyvernSettings(),
    )

    assert result is True


def test_structurally_different_perturbation_is_not_ipt_consistent():
    result = evaluate_ipt(
        original_elements=ORIGINAL,
        perturbation_element_sets=[
            ORIGINAL,
            _elements(("part", "vehicle.engine")),
        ],
        settings=SyvernSettings(),
    )

    assert result is False


def test_missing_or_empty_perturbations_are_unevaluated():
    assert evaluate_ipt(
        original_elements=_elements(("part", "vehicle.engine")),
        perturbation_element_sets=None,
        settings=SyvernSettings(),
    ) is None
    assert evaluate_ipt(
        original_elements=_elements(("part", "vehicle.engine")),
        perturbation_element_sets=[],
        settings=SyvernSettings(),
    ) is None


def test_missing_original_output_is_unevaluated_even_with_perturbations():
    assert evaluate_ipt(
        original_elements=[],
        perturbation_element_sets=[_elements(("part", "vehicle.engine"))],
        settings=SyvernSettings(),
    ) is None


def test_blank_perturbation_is_inconsistent_when_ipt_is_eligible():
    assert evaluate_ipt(
        original_elements=_elements(("part", "vehicle.engine")),
        perturbation_element_sets=[[]],
        settings=SyvernSettings(),
    ) is False


def test_ipt_compares_perturbed_outputs_to_original_output_not_external_reference():
    result = evaluate_ipt(
        original_elements=ORIGINAL,
        perturbation_element_sets=[ORIGINAL],
        settings=SyvernSettings(),
    )

    assert result is True
