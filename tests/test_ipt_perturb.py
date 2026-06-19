import pytest

from syvern.ipt_perturb import generate_perturbations


SPEC = "The vehicle engine shall provide power and report mass in kg."


class FakePerturbationGenerator:
    def __init__(self, variants: list[str], fail: bool = False) -> None:
        self.variants = variants
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def generate(self, spec: str, n: int) -> list[str]:
        self.calls.append((spec, n))
        if self.fail:
            raise RuntimeError("backend unavailable")
        return self.variants


def test_generate_perturbations_returns_deterministic_limited_variants():
    first = generate_perturbations(SPEC, 4)
    second = generate_perturbations(SPEC, 4)

    assert first == second
    assert len(first) == 4
    assert len(set(first)) == 4
    assert SPEC not in first


def test_generate_perturbations_applies_rule_based_equivalent_rewrites():
    variants = generate_perturbations(SPEC, 8)
    joined = "\n".join(variants).lower()

    assert "must provide" in joined
    assert "motor" in joined
    assert "kilogram" in joined
    assert "mass in kg and the vehicle engine shall provide power" in joined


def test_generate_perturbations_handles_empty_inputs():
    assert generate_perturbations("", 3) == []
    assert generate_perturbations("   ", 3) == []
    assert generate_perturbations(SPEC, 0) == []


def test_generate_perturbations_rejects_negative_counts():
    with pytest.raises(ValueError, match="n must not be negative"):
        generate_perturbations(SPEC, -1)


def test_generate_perturbations_can_use_optional_external_generator():
    generator = FakePerturbationGenerator(
        [
            " The vehicle motor shall provide power. ",
            "The vehicle motor shall provide power.",
            SPEC,
        ]
    )

    variants = generate_perturbations(SPEC, 3, generator=generator)

    assert generator.calls == [(SPEC, 3)]
    assert variants == ["The vehicle motor shall provide power."]


def test_generate_perturbations_falls_back_to_rules_when_external_generator_fails():
    generator = FakePerturbationGenerator([], fail=True)

    variants = generate_perturbations(SPEC, 2, generator=generator)

    assert generator.calls == [(SPEC, 2)]
    assert variants == generate_perturbations(SPEC, 2)
