import pytest

from syvern.calibration import cohen_kappa, evaluate_calibration
from syvern.settings import SyvernSettings


def test_cohen_kappa_is_one_for_exact_agreement():
    assert cohen_kappa([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5]) == 1.0


def test_cohen_kappa_is_below_threshold_for_poor_agreement():
    kappa = cohen_kappa([0, 0, 1, 1, 2, 2], [5, 5, 4, 4, 3, 3])

    assert kappa < SyvernSettings().kappa_min


def test_cohen_kappa_handles_degenerate_single_class_cases():
    assert cohen_kappa([0, 0, 0], [0, 0, 0]) == 1.0
    assert cohen_kappa([0, 0, 0], [1, 1, 1]) == 0.0


def test_evaluate_calibration_reports_pass_status():
    passed = evaluate_calibration([1, 2, 3], [1, 2, 3], SyvernSettings())
    failed = evaluate_calibration([0, 0, 1, 1, 2, 2], [5, 5, 4, 4, 3, 3], SyvernSettings())

    assert passed.kappa == 1.0
    assert passed.passed is True
    assert failed.passed is False


def test_cohen_kappa_rejects_empty_labels():
    with pytest.raises(ValueError, match="must not be empty"):
        cohen_kappa([], [])


def test_cohen_kappa_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        cohen_kappa([1], [1, 2])


def test_cohen_kappa_rejects_out_of_range_labels():
    with pytest.raises(ValueError, match="0..5"):
        cohen_kappa([0, 6], [0, 5])


@pytest.mark.parametrize(
    ("human_labels", "judge_labels"),
    [
        ([True], [1]),
        ([1], [False]),
        ([1.0], [1]),
        ([1], [1.0]),
        (["1"], [1]),
        ([1], ["1"]),
    ],
)
def test_cohen_kappa_rejects_non_integer_label_types(human_labels, judge_labels):
    with pytest.raises(ValueError, match="0..5"):
        cohen_kappa(human_labels, judge_labels)
