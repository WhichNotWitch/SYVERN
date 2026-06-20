from __future__ import annotations


def increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def keep_ratio(kept: int, read: int) -> float:
    return kept / read if read else 0.0
