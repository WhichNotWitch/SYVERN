from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CoverageItem:
    name: str
    matched: bool
    evidence: list[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    sample_id: str | None
    backend: str
    score: float
    passed: bool
    required_items: list[CoverageItem]
    missing_items: list[str]
    evidence_type: str
    notes: list[str] = field(default_factory=list)
