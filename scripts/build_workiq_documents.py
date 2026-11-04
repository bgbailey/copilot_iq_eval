"""Build the Work IQ documents (workiq/documents/*.docx) from workiq/content.yaml and the golden facts.

    uv run python scripts/build_workiq_documents.py          # write the .docx files
    uv run python scripts/build_workiq_documents.py --check  # exit 1 if a committed file is stale

The documents are committed, so ``evals deploy workiq`` needs nothing beyond the package itself;
python-docx is a dev dependency used only here. ``--check`` compares the text of each committed
file with what the content pack renders (the bytes differ on every build, because .docx files are
zip archives with timestamps). tests/unit/test_workiq_content.py runs the same comparison.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from copilot_evals.golden import load_golden_set
from copilot_evals.schemas import DocumentRole
from copilot_evals.setup.workiq import (
    CONTENT_FILE,
    DOCUMENTS_DIR,
    RenderedDocument,
    docx_text,
    load_content_pack,
    render_document,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "evals" / "golden"

#: Document properties use a fixed date so rebuilding does not change what readers see.
DOCUMENT_DATE = datetime(2024, 7, 1, 9, 0, tzinfo=UTC)
FOOTER = "Synthetic content for the copilot-fabriciq-evals demo. Contoso is a fictional company."


def write_docx(document: RenderedDocument, path: Path, *, draft: bool) -> None:
    """Write one document with Word's built-in styles: title, headings, bullets and a grid table."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    word = Document()
    properties = word.core_properties
    properties.title = document.title
    properties.author = document.author
    properties.last_modified_by = document.author
    properties.subject = "Synthetic Contoso content (workiq/content.yaml)"
    properties.comments = FOOTER
    properties.created = DOCUMENT_DATE
    properties.modified = DOCUMENT_DATE
    properties.revision = 1

    for block in document.blocks:
        if block.kind == "title":
            word.add_heading(block.text, level=0)
        elif block.kind == "heading":
            word.add_heading(block.text, level=1)
        elif block.kind == "meta":
            run = word.add_paragraph().add_run(block.text)
            run.italic = True
            run.bold = draft
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00) if draft else RGBColor(0x59, 0x59, 0x59)
        elif block.kind == "paragraph":
            word.add_paragraph(block.text)
        elif block.kind == "bullets":
            for item in block.items:
                word.add_paragraph(item, style="List Bullet")
        else:
            table = word.add_table(rows=1, cols=len(block.columns))
            table.style = "Light Grid Accent 1"
            for cell, name in zip(table.rows[0].cells, block.columns, strict=True):
                cell.text = name
            for row in block.rows:
                for cell, value in zip(table.add_row().cells, row, strict=True):
                    cell.text = value
    word.sections[0].footer.paragraphs[0].text = FOOTER
    path.parent.mkdir(parents=True, exist_ok=True)
    word.save(str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if a committed document is stale")
    args = parser.parse_args()

    golden = load_golden_set(GOLDEN_DIR)
    pack = load_content_pack(ROOT / CONTENT_FILE, golden)
    stale = []
    for key, content in pack.documents.items():
        document = render_document(key, content, golden)
        path = ROOT / DOCUMENTS_DIR / document.file_name
        if args.check:
            if not path.is_file() or docx_text(path) != document.plain_text().split("\n"):
                stale.append(path.relative_to(ROOT).as_posix())
            continue
        write_docx(document, path, draft=golden.documents[key].role == DocumentRole.DECOY)
        print(f"built {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("stale (run python scripts/build_workiq_documents.py):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
