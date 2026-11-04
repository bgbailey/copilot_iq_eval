"""Build the Fabric notebooks (.ipynb) from their Python sources.

The notebooks in ``fabric/notebooks/`` are generated from ``fabric/notebooks/src/*.py`` so they can
be reviewed, linted and unit-tested as ordinary Python. Each source is split into cells at lines
that start with ``# %%``:

    # %% [markdown]      a Markdown cell; every line starts with "# " (or is "#")
    # %% [parameters]    the Fabric parameter cell (tagged "parameters"; job parameters override it)
    # %% [logic]         pure Python (pandas/numpy, no Spark), executed by tests/unit/test_notebooks.py
    # %%                 an ordinary code cell (Spark, Fabric utilities)

The output is deterministic, so a unit test can check that every committed notebook matches its
source. The deployment (``evals deploy fabric``) fills in the default lakehouse IDs at import time.

Usage:
    python scripts/build_notebooks.py           # rebuild every notebook
    python scripts/build_notebooks.py --check   # exit 1 if a committed notebook is out of date
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "fabric" / "notebooks" / "src"
OUTPUT_DIR = ROOT / "fabric" / "notebooks"

#: Notebook name -> the lakehouse each notebook runs against by default (PLAN §4.1).
DEFAULT_LAKEHOUSE = {
    "nb_01_generate_data": "lh_gold",
    "nb_02_build_models": "lh_gold",
    "nb_03_validate_and_snapshot": "lh_gold",
}

_KNOWN_KINDS = {"markdown", "parameters", "logic"}


def parse_cells(source: str) -> list[tuple[str, str]]:
    """Split a source file into ``(kind, text)`` cells; ``kind`` is markdown, parameters, logic or code."""
    cells: list[tuple[str, list[str]]] = []
    for line in source.splitlines():
        if line.startswith("# %%"):
            label = line[len("# %%") :].strip()
            kind = label.strip("[]") if label else "code"
            if kind not in _KNOWN_KINDS | {"code"}:
                raise ValueError(f"unknown cell kind {label!r}")
            cells.append((kind, []))
        elif cells:
            cells[-1][1].append(line)
        elif line.strip() and not line.startswith(("#", '"""')):
            raise ValueError("code before the first '# %%' cell marker")
    return [(kind, _clean(kind, lines)) for kind, lines in cells]


def _clean(kind: str, lines: list[str]) -> str:
    """Strip blank edge lines; for Markdown cells, remove the leading '# ' comment prefix."""
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    if kind == "markdown":
        lines = [line[2:] if line.startswith("# ") else line.lstrip("#") for line in lines]
    return "\n".join(lines)


def build_notebook(name: str, source: str) -> dict[str, object]:
    """The .ipynb document for one notebook source."""
    cells = []
    for index, (kind, text) in enumerate(parse_cells(source)):
        lines = [line + "\n" for line in text.split("\n")]
        lines[-1] = lines[-1].rstrip("\n")
        cell: dict[str, object] = {
            "cell_type": "markdown" if kind == "markdown" else "code",
            "id": f"{name}-{index:02d}",
            "metadata": {"tags": [kind]} if kind in {"parameters", "logic"} else {},
            "source": lines,
        }
        if kind != "markdown":
            cell["execution_count"] = None
            cell["outputs"] = []
        cells.append(cell)
    return {
        "cells": cells,
        "metadata": {
            "kernel_info": {"name": "synapse_pyspark"},
            "kernelspec": {"display_name": "Synapse PySpark", "language": "Python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
            "microsoft": {"language": "python", "language_group": "synapse_pyspark"},
            "dependencies": {"lakehouse": {"default_lakehouse_name": DEFAULT_LAKEHOUSE[name]}},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def render(name: str, source: str) -> str:
    """The notebook as committed: indented JSON with a final newline."""
    return json.dumps(build_notebook(name, source), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail if a committed notebook is out of date.")
    args = parser.parse_args()

    stale = []
    for path in sorted(SOURCE_DIR.glob("nb_*.py")):
        target = OUTPUT_DIR / f"{path.stem}.ipynb"
        text = render(path.stem, path.read_text(encoding="utf-8"))
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(target.name)
        else:
            target.write_text(text, encoding="utf-8", newline="\n")
            print(f"built {target.relative_to(ROOT)}")
    if stale:
        print(f"out of date: {', '.join(stale)}. Run: python scripts/build_notebooks.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
