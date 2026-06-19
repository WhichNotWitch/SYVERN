from __future__ import annotations

import re

from syvern.normalization import normalize_ws


_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("shall", "must"),
    ("engine", "motor"),
    ("kg", "kilogram"),
    ("vehicle", "car"),
    ("provide", "deliver"),
    ("mass", "weight"),
    ("report", "publish"),
    ("power", "output power"),
    ("must", "shall"),
    ("motor", "engine"),
    ("kilogram", "kg"),
    ("car", "vehicle"),
    ("deliver", "provide"),
    ("weight", "mass"),
    ("publish", "report"),
)


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[0].isupper():
        return replacement.capitalize()
    return replacement


def _replace_once(text: str, source: str, replacement: str) -> str | None:
    pattern = re.compile(rf"\b{re.escape(source)}\b", flags=re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        return _match_case(match.group(0), replacement)

    updated, count = pattern.subn(replace, text, count=1)
    if count == 0:
        return None
    return normalize_ws(updated)


def _swap_reported_clause(text: str) -> str | None:
    match = re.match(
        r"^(?P<head>.+?)\s+and\s+report\s+(?P<tail>[^.]+)\.?$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    head = match.group("head")
    tail = match.group("tail")
    reordered_head = head[:1].lower() + head[1:]
    return normalize_ws(f"{tail.capitalize()} and {reordered_head}.")


def _add_candidate(candidates: list[str], seen: set[str], original: str, candidate: str | None) -> None:
    if not candidate:
        return
    normalized = normalize_ws(candidate)
    if not normalized or normalized == original or normalized in seen:
        return
    candidates.append(normalized)
    seen.add(normalized)


def _rule_perturbations(original: str, n: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for source, replacement in _REPLACEMENTS[:3]:
        _add_candidate(candidates, seen, original, _replace_once(original, source, replacement))
    _add_candidate(candidates, seen, original, _swap_reported_clause(original))
    for source, replacement in _REPLACEMENTS[3:]:
        _add_candidate(candidates, seen, original, _replace_once(original, source, replacement))

    for first_source, first_replacement in _REPLACEMENTS:
        first = _replace_once(original, first_source, first_replacement)
        if first is None:
            continue
        for second_source, second_replacement in _REPLACEMENTS:
            if len(candidates) >= n:
                return candidates[:n]
            second = _replace_once(first, second_source, second_replacement)
            _add_candidate(candidates, seen, original, second)

    return candidates[:n]


def _external_perturbations(spec: str, original: str, n: int, generator: object) -> list[str]:
    try:
        raw_variants = getattr(generator, "generate")(spec, n)
    except Exception:
        return []
    if not isinstance(raw_variants, list):
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    for raw_variant in raw_variants:
        if not isinstance(raw_variant, str):
            continue
        _add_candidate(candidates, seen, original, raw_variant)
        if len(candidates) >= n:
            return candidates
    return candidates


def generate_perturbations(spec: str, n: int, generator: object | None = None) -> list[str]:
    if n < 0:
        raise ValueError("n must not be negative")
    original = normalize_ws(spec)
    if n == 0 or not original:
        return []

    if generator is not None:
        external = _external_perturbations(spec, original, n, generator)
        if external:
            return external

    return _rule_perturbations(original, n)
