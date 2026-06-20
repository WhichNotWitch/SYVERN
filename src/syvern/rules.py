from __future__ import annotations

from collections import Counter
import re

from syvern.models import ElementSummary, Violation
from syvern.normalization import normalize_ws
from syvern.settings import SyvernSettings


SEVERITY_WEIGHTS = {"warn": 1, "error": 2}
PLACEHOLDER_NAMES = {"foo", "bar", "baz", "example", "placeholder", "sample", "dummy"}
PLACEHOLDER_NAME_RE = re.compile(r"^(item|element|thing|object|part)\d+$")
NUMERIC_SUFFIX_RE = re.compile(r"\d+$")

# Filler markers only count as gaming when they stand alone in model substance,
# not as a segment of a qualified name (e.g. the SysML requirement status enum
# value `StatusKind::tbd`) — the look-around rejects neighbouring `\w . :`.
FILLER_MARKER_RE = re.compile(r"(?<![\w.:])(?:todo|tbd|filler|dummy)(?![\w.:])")
# Comments and string/doc literals are documentation, not model substance, and
# are stripped before the filler scan so legitimate prose does not veto a model.
_COMMENT_OR_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*.*?\*/', re.DOTALL)


def strip_comments_and_strings(text: str) -> str:
    return _COMMENT_OR_STRING_RE.sub(" ", text)


def last_name_segment(qualified_name: str) -> str:
    return qualified_name.rsplit(".", 1)[-1]


def is_placeholder_name(qualified_name: str) -> bool:
    segment = last_name_segment(qualified_name)
    return segment in PLACEHOLDER_NAMES or PLACEHOLDER_NAME_RE.match(segment) is not None


def enumeration_base_name(qualified_name: str) -> str:
    return NUMERIC_SUFFIX_RE.sub("", last_name_segment(qualified_name)) or last_name_segment(qualified_name)


def evaluate_rules(text: str, elements: list[ElementSummary], settings: SyvernSettings) -> list[Violation]:
    normalized = normalize_ws(text).lower()
    violations: list[Violation] = []

    prose = normalize_ws(strip_comments_and_strings(text)).lower()
    if FILLER_MARKER_RE.search(prose) or "???" in prose:
        violations.append(Violation(rule="no_filler_text", severity="error", category="anti_gaming"))

    words = normalized.split()
    if words:
        most_common = Counter(words).most_common(1)[0][1]
        if most_common / len(words) > settings.repetition_ratio:
            violations.append(Violation(rule="no_excessive_repetition", severity="error", category="anti_gaming"))

    if 0 < len(words) < settings.min_tokens:
        violations.append(Violation(rule="minimum_model_signal", severity="warn", category="anti_gaming"))

    # NOTE (Bug2): no `minimum_element_signal` rule. The curated element subset
    # (part/attribute/…) omits valid constructs (`metadata def`, `enum def`,
    # anonymous `action {}`), so an empty subset is not evidence of an
    # element-poor model. Substance is signalled by tokens + the authoritative
    # L0 verdict, not by this scoring subset. See
    # doc/syvern_bug2_element_degeneracy_fix.md.

    if any(is_placeholder_name(element.qualified_name) for element in elements):
        violations.append(Violation(rule="no_placeholder_names", severity="error", category="anti_gaming"))

    if elements:
        groups = Counter((element.type, enumeration_base_name(element.qualified_name)) for element in elements)
        largest_group = max(groups.values(), default=0)
        if largest_group >= settings.enum_min_group_size and largest_group / len(elements) > settings.enum_ratio:
            violations.append(Violation(rule="no_enumeration_gaming", severity="error", category="anti_gaming"))

    return violations


def weighted_violations(violations: list[Violation]) -> int:
    return sum(SEVERITY_WEIGHTS[v.severity] for v in violations)
