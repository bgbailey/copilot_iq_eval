"""Verify relative Markdown links and image targets across repository documentation.

Skips fenced code blocks, inline code spans, external URLs (http/https/mailto/data),
pure in-page #anchors, and historical planning snapshots (docs/PLAN.md, docs/APPROACH_REVIEW.md).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".venv",
    ".copilot",
    ".cache",
    "node_modules",
    "runs",
    "build",
    "dist",
    "__pycache__",
}

SKIP_REL_FILES = {
    Path("docs/PLAN.md"),
    Path("docs/APPROACH_REVIEW.md"),
}

EXTERNAL_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "data:",
    "vscode:",
)

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def iter_markdown_files(root: Path = ROOT) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel in SKIP_REL_FILES:
            continue
        found.append(path)
    return found


def _clean_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    # Strip optional title: path/to/file.md "Title"
    if " " in target and (target.endswith('"') or target.endswith("'")):
        target = target.split(" ", 1)[0].strip()
    # Strip fragment (#section) and query string (?raw=1)
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    return unquote(target)


def check_file_links(md_path: Path, root: Path = ROOT) -> tuple[int, list[str]]:
    errors: list[str] = []
    checked_count = 0
    in_fence = False
    fence_marker = ""

    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, raw_line in enumerate(lines, start=1):
        fence_match = FENCE_RE.match(raw_line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
            elif marker[0] == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue

        scrubbed = INLINE_CODE_RE.sub("", raw_line)
        for match in LINK_RE.finditer(scrubbed):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith("#"):
                continue
            lowered = raw_target.lower()
            if lowered.startswith(EXTERNAL_PREFIXES):
                continue
            cleaned = _clean_target(raw_target)
            if not cleaned:
                continue
            checked_count += 1
            if cleaned.startswith("/"):
                candidate = (root / cleaned.lstrip("/")).resolve()
            else:
                candidate = (md_path.parent / cleaned).resolve()
            if not candidate.exists():
                rel_md = md_path.relative_to(root)
                errors.append(f"{rel_md}:{line_no}: broken relative link -> {raw_target}")

    return checked_count, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root directory")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    md_files = iter_markdown_files(root)
    total_links = 0
    all_errors: list[str] = []

    for md_file in md_files:
        count, errs = check_file_links(md_file, root)
        total_links += count
        all_errors.extend(errs)

    if all_errors:
        print(f"Found {len(all_errors)} broken relative link(s):", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"Checked {total_links} relative links across {len(md_files)} Markdown files (0 broken).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
