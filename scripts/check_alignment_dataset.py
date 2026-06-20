#!/usr/bin/env python3
"""Validate a SYVERN human-truth alignment dataset against the Phase 1 spec.

Spec: doc/alignment_dataset_spec.md. Standalone (stdlib only).

Usage:
    python scripts/check_alignment_dataset.py --in manual_v1.jsonl --profile manual_v1
    python scripts/check_alignment_dataset.py --in data/alignment/alignment_seed_template.jsonl --profile seed

Exit code 0 iff there are no errors (and, under --strict, no warnings).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

CATEGORIES = ("valid", "syntax", "unresolved", "type", "nested")

# Truth shape per category: (parse_ok, resolve_ok, typecheck_ok, keep_expected).
# None means the stage is not reached and must be labelled null.
CATEGORY_TRUTH = {
    "valid": (True, True, True, True),
    "nested": (True, True, True, True),
    "syntax": (False, None, None, False),
    "unresolved": (True, False, None, False),
    "type": (True, True, False, False),
}

# Stub adapter markers (see src/syvern/adapters/stub.py). Real text must avoid
# them or stub-based smoke tests get corrupted.
STUB_TRIGGER_WORDS = ("syntax_error", "unresolved_ref", "type_error", "parser_disagreement")

PROFILES = {
    "seed": {"valid": 2, "syntax": 2, "unresolved": 2, "type": 2, "nested": 2},
    "manual_v1": {"valid": 22, "syntax": 10, "unresolved": 10, "type": 10, "nested": 8},
}

REQUIRED_FIELDS = ("case_id", "category", "text", "parse_ok", "resolve_ok", "typecheck_ok", "keep_expected")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _check_record(rec: dict, where: str, report: Report) -> str | None:
    """Validate one record; return its category if usable for quota counting."""
    for field in REQUIRED_FIELDS:
        if field not in rec:
            report.error(where, f"missing required field '{field}'")
            return None

    case_id = rec["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        report.error(where, "case_id must be a non-empty string")

    category = rec["category"]
    if category not in CATEGORIES:
        report.error(where, f"category '{category}' not in {CATEGORIES}")
        return None

    text = rec["text"]
    if not isinstance(text, str) or not text.strip():
        report.error(where, "text must be a non-empty string")
        text = ""

    if not _is_bool(rec["parse_ok"]):
        report.error(where, "parse_ok must be a bool")
    if not _is_bool(rec["keep_expected"]):
        report.error(where, "keep_expected must be a bool")
    for stage in ("resolve_ok", "typecheck_ok"):
        if not (rec[stage] is None or _is_bool(rec[stage])):
            report.error(where, f"{stage} must be a bool or null")

    if "expected_elements" in rec and rec["expected_elements"] is not None:
        if not isinstance(rec["expected_elements"], list):
            report.error(where, "expected_elements must be a list or null")

    # Cascade: unreached stages must be null.
    if rec["parse_ok"] is False:
        if rec["resolve_ok"] is not None:
            report.error(where, "parse_ok=false requires resolve_ok=null (stage not reached)")
        if rec["typecheck_ok"] is not None:
            report.error(where, "parse_ok=false requires typecheck_ok=null (stage not reached)")
    elif rec["resolve_ok"] is False and rec["typecheck_ok"] is not None:
        report.error(where, "resolve_ok=false requires typecheck_ok=null (stage not reached)")

    # keep_expected == clean T0.
    clean_t0 = rec["parse_ok"] is True and rec["resolve_ok"] is True and rec["typecheck_ok"] is True
    if rec["keep_expected"] is not clean_t0:
        report.error(where, f"keep_expected must equal clean-T0 ({clean_t0}); got {rec['keep_expected']}")

    # Category ⇄ truth contract.
    expected = CATEGORY_TRUTH[category]
    actual = (rec["parse_ok"], rec["resolve_ok"], rec["typecheck_ok"], rec["keep_expected"])
    if actual != expected:
        report.error(
            where,
            f"category '{category}' requires (parse,resolve,typecheck,keep)={expected}; got {actual}",
        )

    # Stub trigger words (warning).
    lowered = text.lower()
    for marker in STUB_TRIGGER_WORDS:
        if marker in lowered:
            report.warn(where, f"text contains stub trigger word '{marker}'")

    return category


def check_dataset(path: str, profile: str | None) -> Report:
    report = Report()
    categories: Counter[str] = Counter()
    seen_ids: set[str] = set()
    seen_text: dict[str, str] = {}
    total = 0

    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as exc:
        report.error(path, f"cannot read file: {exc}")
        return report

    for n, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        where = f"{path}:{n}"
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError as exc:
            report.error(where, f"invalid JSON: {exc}")
            continue
        if not isinstance(rec, dict):
            report.error(where, "line is not a JSON object")
            continue

        total += 1
        cid = rec.get("case_id")
        if isinstance(cid, str):
            if cid in seen_ids:
                report.error(where, f"duplicate case_id '{cid}'")
            seen_ids.add(cid)
        txt = rec.get("text")
        if isinstance(txt, str):
            norm = " ".join(txt.split())
            if norm in seen_text:
                report.warn(where, f"duplicate text (same as {seen_text[norm]})")
            else:
                seen_text[norm] = cid if isinstance(cid, str) else where

        category = _check_record(rec, where, report)
        if category:
            categories[category] += 1

    if total == 0:
        report.error(path, "dataset contains no records")

    if profile:
        quota = PROFILES[profile]
        for category, want in quota.items():
            have = categories.get(category, 0)
            if have != want:
                report.error(path, f"quota '{profile}': category '{category}' needs {want}, has {have}")

    print(f"records: {total}  by category: {dict(sorted(categories.items()))}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a SYVERN alignment dataset.")
    parser.add_argument("--in", dest="path", required=True, help="dataset JSONL path")
    parser.add_argument("--profile", choices=sorted(PROFILES), default=None, help="enforce a quota profile")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    report = check_dataset(args.path, args.profile)

    for w in report.warnings:
        print(f"WARN  {w}")
    for e in report.errors:
        print(f"ERROR {e}")
    print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s)")

    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
