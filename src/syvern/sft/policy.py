from __future__ import annotations

from syvern.coverage.schema import CoverageReport


def decide_sft_keep(
    validation_result,
    coverage_report: CoverageReport | None,
    *,
    require_coverage: bool = True,
    min_coverage: float = 0.6,
) -> tuple[bool, str]:
    if not validation_result.stage.parse.ok:
        return False, "parse_failed"
    if not validation_result.stage.resolve.ok:
        return False, "resolve_failed"
    if not validation_result.stage.typecheck.ok:
        return False, "typecheck_failed"
    if validation_result.veto.triggered:
        return False, "vetoed"
    if require_coverage:
        if coverage_report is None:
            return False, "coverage_missing"
        if not coverage_report.passed or coverage_report.score < min_coverage:
            return False, "low_requirement_coverage"
    return True, "passed"
