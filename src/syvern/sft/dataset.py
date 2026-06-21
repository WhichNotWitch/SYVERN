from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


CONSTRUCT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("package", re.compile(r"\bpackage\b")),
    ("part", re.compile(r"\bpart\s+(def\b|[A-Za-z_])")),
    ("attribute", re.compile(r"\battribute\s+(def\b|[A-Za-z_])")),
    ("item", re.compile(r"\bitem\s+(def\b|[A-Za-z_])")),
    ("port", re.compile(r"\bport\s+(def\b|[A-Za-z_])")),
    ("state", re.compile(r"\bstate\s+(def\b|[A-Za-z_])")),
    ("action", re.compile(r"\baction\s+(def\b|[A-Za-z_])")),
    ("constraint", re.compile(r"\bconstraint\s+(def\b|[A-Za-z_])")),
    ("requirement", re.compile(r"\brequirement\s+(def\b|[A-Za-z_])")),
    ("connection", re.compile(r"\b(connect|connection)\b")),
    ("interface", re.compile(r"\binterface\s+(def\b|[A-Za-z_])")),
    ("redefinition", re.compile(r"\b(redefines|redefinition)\b")),
    ("subsetting", re.compile(r"\b(subsets|subsetting)\b")),
)


@dataclass(frozen=True)
class SourceSpec:
    root: Path
    repo: str
    commit: str
    license: str


def build_sft_candidates(
    sources: Iterable[SourceSpec],
    *,
    seed_paths: Iterable[Path] = (),
    max_chars: int = 20_000,
    merge_by_folder: bool = False,
) -> list[dict[str, Any]]:
    """Build candidate (instruction -> SysML) records from source checkouts.

    With ``merge_by_folder`` the ``.sysml`` files in each directory are
    concatenated into a single record. Official SysML v2 examples are organised
    so that all files in one folder together form one complete model (they
    cross-import siblings); validating them per file makes those imports
    unresolvable and wrongly rejects valid models. The folder is the correct
    validation unit.
    """
    records: list[dict[str, Any]] = []
    for source in sources:
        if merge_by_folder:
            records.extend(_folder_records(source, max_chars))
        else:
            for path in _iter_sysml_files(source.root):
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if not text or len(text) > max_chars:
                    continue
                records.append(_record_from_file(path, source, text))
    for seed_path in seed_paths:
        records.extend(_load_jsonl(seed_path))
    return records


def coverage_counts(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        constructs = record.get("constructs", [])
        if not isinstance(constructs, list):
            continue
        for construct in constructs:
            if isinstance(construct, str):
                counts[construct] = counts.get(construct, 0) + 1
    return dict(sorted(counts.items()))


def dedupe_by_output(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    for record in records:
        key = _normalize_output(str(record.get("output", "")))
        if key in seen:
            duplicate_ids.append(str(record.get("id", "")))
            continue
        seen.add(key)
        kept.append(record)
    return kept, duplicate_ids


def split_by_source_file(
    records: list[dict[str, Any]],
    *,
    val_ratio: float = 0.1,
    seed: int = 17,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source = record.get("source")
        path = str(source.get("path")) if isinstance(source, dict) else str(record.get("id", ""))
        groups.setdefault(path, []).append(record)

    paths = sorted(groups)
    rng = random.Random(seed)
    rng.shuffle(paths)
    val_group_count = max(1, int(round(len(paths) * val_ratio))) if len(paths) > 1 else 0
    val_paths = set(paths[:val_group_count])
    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for path in sorted(groups):
        (val if path in val_paths else train).extend(groups[path])
    return train, val


def detect_constructs(text: str) -> list[str]:
    return [name for name, pattern in CONSTRUCT_PATTERNS if pattern.search(text)]


_PACKAGE_START = re.compile(r"(?:\blibrary\s+)?\bpackage\b")


def split_top_level_packages(text: str) -> list[str]:
    """Return the source of each top-level ``package`` / ``library package`` block.

    Brace-matched, skipping braces inside line/block comments and string
    literals. Used to decompose a large multi-package model into individual
    self-contained sub-models (each is re-validated by the caller).
    """
    blocks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        match = _PACKAGE_START.search(text, i)
        if not match:
            break
        start = match.start()
        brace = text.find("{", match.end())
        if brace < 0:
            break
        depth = 0
        j = brace
        while j < n:
            c = text[j]
            if c == "/" and j + 1 < n and text[j + 1] == "/":
                j = text.find("\n", j)
                if j < 0:
                    j = n
                continue
            if c == "/" and j + 1 < n and text[j + 1] == "*":
                end = text.find("*/", j + 2)
                j = n if end < 0 else end + 2
                continue
            if c == '"':
                j += 1
                while j < n and text[j] != '"':
                    j += 2 if text[j] == "\\" else 1
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(text[start : j + 1])
        i = j + 1
    return blocks


def decompose_records(
    records: Iterable[dict[str, Any]],
    validator: "Any",
    *,
    seen_outputs: set[str],
    min_chars: int = 80,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Split multi-package models into self-contained single-package sub-models.

    ``validator(text) -> bool`` reports whether a package passes the data_filter
    gate standalone. Only packages that are not already seen (``seen_outputs``,
    mutated in place) and pass standalone are emitted, each carrying
    ``source.decomposed_from``. Single-package models are left untouched.
    """
    new: list[dict[str, Any]] = []
    tested = passed = 0
    for record in records:
        blocks = split_top_level_packages(str(record.get("output", "")))
        if len(blocks) < 2:
            continue
        for block in blocks:
            block = block.strip()
            if len(block) < min_chars:
                continue
            key = _normalize_output(block)
            if key in seen_outputs:
                continue
            tested += 1
            if not validator(block):
                continue
            passed += 1
            seen_outputs.add(key)
            constructs = detect_constructs(block)
            digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:12]
            source = dict(record.get("source") or {})
            source["decomposed_from"] = record.get("id")
            new.append(
                {
                    "id": f"decomp_{digest}",
                    "instruction": _instruction_for_constructs(constructs),
                    "input": "",
                    "output": block,
                    "constructs": constructs,
                    "source": source,
                }
            )
    return new, {"tested": tested, "passed": passed, "added": len(new)}


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _iter_sysml_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.sysml")):
        if any(part.startswith(".") or part in {"build", "target", "node_modules"} for part in path.parts):
            continue
        yield path


def _folder_records(source: SourceSpec, max_chars: int) -> list[dict[str, Any]]:
    groups: dict[Path, list[Path]] = {}
    for path in _iter_sysml_files(source.root):
        groups.setdefault(path.parent, []).append(path)
    records: list[dict[str, Any]] = []
    for folder in sorted(groups):
        files = sorted(groups[folder])
        parts: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                parts.append(text)
        if not parts:
            continue
        merged = "\n\n".join(parts)
        if len(merged) > max_chars:
            continue
        records.append(_record_from_folder(folder, files, source, merged))
    return records


def _record_from_folder(
    folder: Path, files: list[Path], source: SourceSpec, text: str
) -> dict[str, Any]:
    relative = folder.relative_to(source.root).as_posix() or "."
    file_names = [path.relative_to(source.root).as_posix() for path in files]
    constructs = detect_constructs(text)
    digest = hashlib.sha256(
        f"{source.repo}|{source.commit}|{relative}|{text}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "id": f"official_{digest}",
        "instruction": _instruction_for_constructs(constructs),
        "input": "",
        "output": text,
        "constructs": constructs,
        "source": {
            "repo": source.repo,
            "commit": source.commit,
            "path": relative,
            "files": file_names,
            "license": source.license,
        },
    }


def _record_from_file(path: Path, source: SourceSpec, text: str) -> dict[str, Any]:
    relative = path.relative_to(source.root).as_posix()
    constructs = detect_constructs(text)
    digest = hashlib.sha256(f"{source.repo}|{source.commit}|{relative}|{text}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"official_{digest}",
        "instruction": _instruction_for_constructs(constructs),
        "input": "",
        "output": text,
        "constructs": constructs,
        "source": {
            "repo": source.repo,
            "commit": source.commit,
            "path": relative,
            "license": source.license,
        },
    }


def _instruction_for_constructs(constructs: list[str]) -> str:
    if not constructs:
        return "Write a valid SysML v2 model."
    if len(constructs) == 1:
        phrase = constructs[0]
    elif len(constructs) == 2:
        phrase = f"{constructs[0]} and {constructs[1]}"
    else:
        phrase = f"{', '.join(constructs[:-1])}, and {constructs[-1]}"
    return f"Write a SysML v2 model covering {phrase} constructs."


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: JSONL records must be objects")
        records.append(payload)
    return records


def _normalize_output(text: str) -> str:
    return " ".join(text.split())
