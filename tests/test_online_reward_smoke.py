from time import perf_counter

from syvern.pipeline import ValidationPipeline


def test_online_reward_local_stub_throughput_smoke():
    pipeline = ValidationPipeline()
    reference = {
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
    intent_reference = {
        "requirements": ["model engine", "include mass"],
        "must_include": ["vehicle.engine", "vehicle.mass"],
        "must_not_include": ["aircraft.wing"],
    }
    samples = [
        "part vehicle.engine attribute vehicle.mass",
        "part B unresolved_ref",
        "part C type_error",
        "part vehicle.engine attribute vehicle.mass",
        "part vehicle.engine attribute vehicle.mass",
    ]

    started = perf_counter()
    responses = [
        pipeline.validate(
            sample,
            mode="online_reward",
            reference=reference,
            perturbations=["attribute vehicle.mass part vehicle.engine"],
            intent_reference=intent_reference,
        )
        for sample in samples
    ]
    elapsed = perf_counter() - started

    assert [response.intent.evaluated for response in responses] == [False, False, False, False, False]
    assert [response.structural.evaluated for response in responses] == [False, False, False, False, False]
    assert [response.robustness.ipt_consistent for response in responses] == [None, None, None, None, None]
    assert elapsed < 1.0
