"""The Work IQ content pack: the Microsoft 365 documents the joint cases rely on (PLAN §4.4, ADR-010).

``workiq/content.yaml`` says where each document goes and what it says; ``evals/golden/models.yaml``
holds the figures (approved targets, service objectives, the draft's wrong number). This module:

* loads the pack and checks it against the golden set (``load_content_pack``): every golden
  document has content, every ``{fact}`` placeholder exists, every fact is stated, and no persona
  without certified data access can read a source document;
* renders a document's blocks with the facts filled in (``render_document``);
  scripts/build_workiq_documents.py turns them into the .docx files in workiq/documents/;
* uploads the built files to the SharePoint sites in settings (``WorkIQSeeder``).

Uploading is idempotent: folders are created when missing and files are replaced.
"""

import html
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from copilot_evals.golden import GoldenSet
from copilot_evals.schemas import DocumentFact, DocumentRole, Key, Unit
from copilot_evals.setup.graph import GraphClient
from copilot_evals.setup.rest import SetupError

CONTENT_FILE = Path("workiq") / "content.yaml"
DOCUMENTS_DIR = Path("workiq") / "documents"

_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>", re.DOTALL)
_TEXT_RUN = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>", re.DOTALL)

BlockKind = Literal["title", "meta", "heading", "paragraph", "bullets", "table"]
_BLOCK_KINDS: tuple[BlockKind, ...] = ("title", "meta", "heading", "paragraph", "bullets", "table")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TableBlock(_Strict):
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def _rows_fit_columns(self) -> Self:
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(f"table row {row} has {len(row)} cells for {len(self.columns)} columns")
        return self


class Block(_Strict):
    """One block of a document; exactly one field is set."""

    title: str | None = None
    meta: str | None = None
    heading: str | None = None
    paragraph: str | None = None
    bullets: list[str] | None = None
    table: TableBlock | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if len(self._set_kinds()) != 1:
            raise ValueError("a block sets exactly one of: title, meta, heading, paragraph, bullets, table")
        return self

    def _set_kinds(self) -> list[BlockKind]:
        return [kind for kind in _BLOCK_KINDS if getattr(self, kind) is not None]

    @property
    def kind(self) -> BlockKind:
        return self._set_kinds()[0]

    def texts(self) -> list[str]:
        """Every text cell in the block, in reading order."""
        if self.table is not None:
            return [*self.table.columns, *(cell for row in self.table.rows for cell in row)]
        if self.bullets is not None:
            return list(self.bullets)
        return [str(getattr(self, self.kind))]


class SiteSpec(_Strict):
    title: str
    readers: list[Key] = Field(min_length=1)


class DocumentContent(_Strict):
    site: Key
    folder: str
    author: str
    blocks: list[Block] = Field(min_length=2)

    @model_validator(mode="after")
    def _starts_with_title(self) -> Self:
        if self.blocks[0].kind != "title":
            raise ValueError("a document starts with a title block")
        return self


class ContentPack(_Strict):
    version: Literal[1]
    sites: dict[Key, SiteSpec]
    documents: dict[Key, DocumentContent]


@dataclass(frozen=True)
class RenderedBlock:
    kind: BlockKind
    text: str = ""
    items: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class RenderedDocument:
    key: str
    file_name: str
    title: str
    author: str
    site: str
    folder: str
    blocks: tuple[RenderedBlock, ...]

    def plain_text(self) -> str:
        """All text in reading order, one block per line (tests compare it with the built .docx)."""
        lines: list[str] = []
        for block in self.blocks:
            cells = [cell for row in block.rows for cell in row]
            lines.extend([block.text] if block.text else [*block.items, *block.columns, *cells])
        return "\n".join(lines)


def format_fact(fact: DocumentFact) -> str:
    """A fact the way a business document writes it: $12,500,000 · 6 hours · 1,234 · 12.5%."""
    value = fact.value
    if fact.unit == Unit.CURRENCY_USD:
        return f"${value:,.0f}" if value == value.to_integral_value() else f"${value:,.2f}"
    if fact.unit == Unit.HOURS:
        return f"{_plain(value)} hour" + ("" if value == 1 else "s")
    if fact.unit == Unit.PERCENT:
        return f"{_plain(value * 100)}%"
    if fact.unit == Unit.COUNT:
        return f"{value:,.0f}"
    return _plain(value)


def _plain(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def fill(text: str, facts: dict[str, DocumentFact], *, where: str) -> str:
    """Replace each ``{fact_key}`` in ``text`` with the formatted fact."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in facts:
            raise SetupError(f"{where}: unknown fact {{{key}}}; facts are {sorted(facts)}")
        return format_fact(facts[key])

    return _PLACEHOLDER.sub(replace, text)


def render_document(key: str, content: DocumentContent, golden: GoldenSet) -> RenderedDocument:
    """A document's blocks with every fact filled in from the golden set."""
    reference = golden.documents[key]
    facts = reference.facts
    where = f"{CONTENT_FILE} documents.{key}"
    blocks: list[RenderedBlock] = []
    for block in content.blocks:
        if block.table is not None:
            rows = tuple(tuple(fill(cell, facts, where=where) for cell in row) for row in block.table.rows)
            blocks.append(RenderedBlock("table", columns=tuple(block.table.columns), rows=rows))
        elif block.bullets is not None:
            items = tuple(fill(item, facts, where=where) for item in block.bullets)
            blocks.append(RenderedBlock("bullets", items=items))
        else:
            blocks.append(RenderedBlock(block.kind, text=fill(block.texts()[0], facts, where=where)))
    return RenderedDocument(
        key=key,
        file_name=reference.title,
        title=blocks[0].text,
        author=content.author,
        site=content.site,
        folder=content.folder,
        blocks=tuple(blocks),
    )


def load_content_pack(content_file: Path, golden: GoldenSet) -> ContentPack:
    """Load the content pack (workiq/content.yaml) and check it against the golden set.

    Raises:
        SetupError: The file is not a valid content pack, or it disagrees with the golden set.
    """
    try:
        pack = ContentPack.model_validate(yaml.safe_load(content_file.read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise SetupError(f"{content_file}: {error}") from error
    problems = check_content_pack(pack, golden)
    if problems:
        raise SetupError(f"{content_file} does not match the golden set:\n  - " + "\n  - ".join(problems))
    return pack


def check_content_pack(pack: ContentPack, golden: GoldenSet) -> list[str]:
    """Every way the content pack and the golden documents can disagree."""
    problems: list[str] = []
    for key in sorted(set(golden.documents) ^ set(pack.documents)):
        side = "has no content in" if key in golden.documents else "is not a golden document, but is in"
        problems.append(f"document {key} {side} {CONTENT_FILE}")
    no_data_access = {key for key, persona in golden.personas.items() if persona.rls_role is None}
    for site_key, site in pack.sites.items():
        problems.extend(f"site {site_key}: unknown persona {p}" for p in site.readers if p not in golden.personas)
    for key, content in pack.documents.items():
        if key not in golden.documents:
            continue
        reference = golden.documents[key]
        site = pack.sites.get(content.site)
        if site is None:
            problems.append(f"document {key}: unknown site {content.site}")
            continue
        if reference.role == DocumentRole.SOURCE and no_data_access & set(site.readers):
            problems.append(f"document {key} is a source, but {sorted(no_data_access & set(site.readers))} can read it")
        if f"{content.blocks[0].title}.docx" != reference.title:
            problems.append(f"document {key}: title block must be the file name without .docx ({reference.title})")
        used = {name for block in content.blocks for text in block.texts() for name in _PLACEHOLDER.findall(text)}
        problems.extend(f"document {key}: unknown fact {{{name}}}" for name in sorted(used - set(reference.facts)))
        problems.extend(f"document {key}: fact {name} is never stated" for name in sorted(set(reference.facts) - used))
    return problems


def docx_text(path: Path) -> list[str]:
    """The non-empty paragraphs of a .docx body (table cells included), in reading order.

    Reads word/document.xml with the standard library only, so the check needs no python-docx.
    """
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    paragraphs = ("".join(html.unescape(text) for text in _TEXT_RUN.findall(p)) for p in _PARAGRAPH.findall(xml))
    return [text for text in paragraphs if text.strip()]


# --- seeding ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeededDocument:
    key: str
    site_url: str
    path: str
    web_url: str


def check_seeding_inputs(pack: ContentPack, golden: GoldenSet, sites: dict[str, str], documents_dir: Path) -> None:
    """Raise SetupError unless every site has a URL in settings and every document has been built."""
    missing_sites = sorted({content.site for content in pack.documents.values()} - set(sites))
    if missing_sites:
        raise SetupError(f"add these sites to [workiq.sites] in config/settings.toml: {', '.join(missing_sites)}")
    for key in pack.documents:
        path = documents_dir / golden.documents[key].title
        if not path.is_file():
            raise SetupError(f"{path} is missing: run python scripts/build_workiq_documents.py")


def seeding_plan(pack: ContentPack, golden: GoldenSet, sites: dict[str, str], documents_dir: Path) -> list[str]:
    """What ``WorkIQSeeder.seed`` would do, without calling any API (``--dry-run``)."""
    check_seeding_inputs(pack, golden, sites, documents_dir)
    lines = []
    for key, content in pack.documents.items():
        readers = ", ".join(pack.sites[content.site].readers)
        lines.append(f"upload {golden.documents[key].title} -> {sites[content.site]} /{content.folder} "
                     f"(site members should be: {readers})")
    return lines


class WorkIQSeeder:
    """Uploads the built documents to their SharePoint sites (``evals deploy workiq``)."""

    def __init__(
        self,
        graph: GraphClient,
        pack: ContentPack,
        golden: GoldenSet,
        sites: dict[str, str],
        documents_dir: Path,
        report: Callable[[str], None] = print,
    ) -> None:
        self._graph = graph
        self._pack = pack
        self._golden = golden
        self._sites = sites
        self._documents_dir = documents_dir
        self._report = report

    def seed(self) -> list[SeededDocument]:
        """Create missing folders and upload (or replace) every document."""
        check_seeding_inputs(self._pack, self._golden, self._sites, self._documents_dir)
        drives: dict[str, str] = {}
        seeded: list[SeededDocument] = []
        for key, content in self._pack.documents.items():
            site_url = self._sites[content.site]
            if content.site not in drives:
                site = self._graph.site(site_url)
                drives[content.site] = str(self._graph.default_drive(str(site["id"]))["id"])
            drive_id = drives[content.site]
            file_name = self._golden.documents[key].title
            folder_id = self._graph.ensure_folder(drive_id, content.folder)
            item: dict[str, Any] = self._graph.upload(
                drive_id, folder_id, file_name, (self._documents_dir / file_name).read_bytes()
            )
            seeded.append(SeededDocument(key, site_url, f"{content.folder}/{file_name}", str(item.get("webUrl", ""))))
            self._report(f"uploaded {file_name} -> {site_url} /{content.folder}")
        return seeded

    def verify(self) -> list[str]:
        """Problems with the uploaded files: missing, or a different size from the built file."""
        check_seeding_inputs(self._pack, self._golden, self._sites, self._documents_dir)
        problems: list[str] = []
        for key, content in self._pack.documents.items():
            site = self._graph.site(self._sites[content.site])
            drive_id = str(self._graph.default_drive(str(site["id"]))["id"])
            file_name = self._golden.documents[key].title
            item = self._graph.item_by_path(drive_id, f"{content.folder}/{file_name}")
            expected = (self._documents_dir / file_name).stat().st_size
            if item is None:
                problems.append(f"{file_name} is missing from {self._sites[content.site]} /{content.folder}")
            elif int(item.get("size", -1)) != expected:
                problems.append(f"{file_name} differs from workiq/documents ({item.get('size')} vs {expected} bytes)")
        return problems
