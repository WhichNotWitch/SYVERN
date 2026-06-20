from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SftSample:
    sample_id: str
    requirement_text: str
    sysml_text: str
    source: str | dict[str, Any]
    task_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_record: dict[str, Any] = field(default_factory=dict)
