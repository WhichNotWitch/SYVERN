from syvern.coverage.simple import SimpleCoverageEvaluator


def test_simple_coverage_matches_required_items_and_aliases():
    evaluator = SimpleCoverageEvaluator(min_coverage=0.6)

    report = evaluator.evaluate(
        "Train shall enter emergency braking when obstacle is detected.",
        "state def TrainMotionControl { state EmergencyStopping; accept ObstacleDetected; }",
        sample_id="train_001",
        metadata={
            "coverage_spec": {
                "required": ["ObstacleDetected", "EmergencyStopping"],
                "aliases": {
                    "obstacle": ["ObstacleDetected"],
                    "emergency braking": ["EmergencyStopping"],
                },
            }
        },
    )

    assert report.sample_id == "train_001"
    assert report.backend == "simple"
    assert report.score == 1.0
    assert report.passed is True
    assert report.missing_items == []
    assert report.evidence_type == "keyword_alias_match"
    assert [item.name for item in report.required_items] == [
        "ObstacleDetected",
        "EmergencyStopping",
    ]
    assert all(item.matched for item in report.required_items)


def test_simple_coverage_reports_missing_items():
    evaluator = SimpleCoverageEvaluator(min_coverage=0.6)

    report = evaluator.evaluate(
        "ObstacleDetected and EmergencyStopping are required.",
        "part def Train { attribute speed; }",
        metadata={"coverage_spec": {"required": ["ObstacleDetected", "EmergencyStopping"]}},
    )

    assert report.score == 0.0
    assert report.passed is False
    assert report.missing_items == ["ObstacleDetected", "EmergencyStopping"]


def test_simple_coverage_extracts_camel_case_tokens_without_spec():
    evaluator = SimpleCoverageEvaluator(min_coverage=0.5)

    report = evaluator.evaluate(
        "When ObstacleDetected occurs, enter EmergencyStopping.",
        "state def Train { accept ObstacleDetected; }",
    )

    assert [item.name for item in report.required_items] == [
        "ObstacleDetected",
        "EmergencyStopping",
    ]
    assert report.score == 0.5
    assert report.passed is True
