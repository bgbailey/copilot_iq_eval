"""Fail if public tracked files contain internal operator jargon, demo-meeting phrasing, or real tenant UPNs."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKIP = {
    "config/wording-denylist.txt",
    "docs/PLAN.md",
    "docs/APPROACH_REVIEW.md",
    "tools/check_public_wording.py",
}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf", ".zip"}


def load_patterns(denylist_path: Path, extra_csv: str = "") -> list[tuple[str, re.Pattern[str]]]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    if denylist_path.is_file():
        for raw in denylist_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("re:"):
                expr = line[3:].strip()
                patterns.append((line, re.compile(expr, re.IGNORECASE)))
            else:
                patterns.append((line, re.compile(re.escape(line), re.IGNORECASE)))
    for token in (extra_csv or "").split(","):
        cleaned = token.strip()
        if cleaned:
            patterns.append((f"env:{cleaned}", re.compile(re.escape(cleaned), re.IGNORECASE)))
    return patterns


def tracked_files(root: Path) -> list[str]:
    out = subprocess.check_output(["git", "-C", str(root), "ls-files"], text=True, encoding="utf-8")
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def scan_files(
    root: Path = ROOT,
    *,
    files: list[str] | None = None,
    denylist_path: Path | None = None,
    extra_csv: str | None = None,
    skip: set[str] | None = None,
) -> list[str]:
    denylist = denylist_path or (root / "config" / "wording-denylist.txt")
    extra = extra_csv if extra_csv is not None else os.environ.get("CFEVAL_PRIVATE_DENYLIST", "")
    compiled = load_patterns(denylist, extra)
    ignored = DEFAULT_SKIP if skip is None else skip
    rel_files = files if files is not None else tracked_files(root)
    findings: list[str] = []
    for rel in rel_files:
        norm = rel.replace("\\", "/")
        if norm in ignored or Path(norm).suffix.lower() in BINARY_SUFFIXES:
            continue
        path = root / norm
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in compiled:
                match = pattern.search(line)
                if match:
                    findings.append(f"{norm}:{lineno}: matched {label!r} -> {match.group(0)!r}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--denylist", type=Path, default=None)
    args = parser.parse_args(argv)
    findings = scan_files(args.root.resolve(), denylist_path=args.denylist)
    if findings:
        for item in findings:
            print(item, file=sys.stderr)
        print(f"Found {len(findings)} public-wording violation(s).", file=sys.stderr)
        return 1
    print("Public wording check passed (0 violations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
