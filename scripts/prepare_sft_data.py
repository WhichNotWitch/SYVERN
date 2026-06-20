#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from syvern.sft_dataset import SourceSpec, build_sft_candidates, coverage_counts, write_jsonl


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare SFT candidates from official SysML v2 .sysml files.")
    parser.add_argument("--source-root", action="append", required=True, help="checkout containing .sysml files")
    parser.add_argument("--repo", action="append", required=True, help="repo label for each source root")
    parser.add_argument("--license", action="append", required=True, help="SPDX license id for each source root")
    parser.add_argument("--seed", action="append", default=[], help="extra seed JSONL to append")
    parser.add_argument("--out", required=True, help="candidate JSONL output")
    parser.add_argument("--report", required=True, help="JSON report path")
    parser.add_argument("--max-chars", type=int, default=20_000)
    args = parser.parse_args(argv)

    if not (len(args.source_root) == len(args.repo) == len(args.license)):
        raise SystemExit("--source-root, --repo, and --license must have matching counts")

    sources = [
        SourceSpec(
            root=Path(root),
            repo=repo,
            commit=_git_commit(Path(root)),
            license=license_id,
        )
        for root, repo, license_id in zip(args.source_root, args.repo, args.license)
    ]
    records = build_sft_candidates(
        sources,
        seed_paths=[Path(path) for path in args.seed],
        max_chars=args.max_chars,
    )
    out = Path(args.out)
    report = Path(args.report)
    write_jsonl(out, records)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "records": len(records),
                "coverage": coverage_counts(records),
                "sources": [
                    {
                        "root": str(source.root),
                        "repo": source.repo,
                        "commit": source.commit,
                        "license": source.license,
                    }
                    for source in sources
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
