from __future__ import annotations

from abc import ABC, abstractmethod

from syvern.coverage.schema import CoverageReport


class CoverageEvaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        requirement_text: str,
        sysml_text: str,
        *,
        sample_id: str | None = None,
        metadata: dict | None = None,
    ) -> CoverageReport:
        """Return requirement coverage evidence for one SFT sample."""
