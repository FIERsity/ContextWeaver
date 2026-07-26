"""Document importers normalize supported formats to reviewable Markdown."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


@dataclass(frozen=True)
class ImportedText:
    markdown: str
    title: str
    source_format: str
    report: dict[str, Any] | None = None


def read_source(path: Path) -> ImportedText:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return ImportedText(path.read_text(encoding="utf-8"), path.stem, "markdown")
    if suffix == ".txt":
        return ImportedText(_txt_to_markdown(path.read_text(encoding="utf-8")), path.stem, "txt")
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".epub":
        return _read_epub(path)
    if suffix in {".xml", ".jats"}:
        return _read_jats(path)
    raise ValueError("Supported source formats: Markdown, TXT, DOCX, EPUB, JATS XML")


def _txt_to_markdown(text: str) -> str:
    return re.sub(r"(?im)^(chapter|part)\s+(.+)$", r"# \1 \2", text)


def _read_docx(path: Path) -> ImportedText:
    from docx import Document
    from docx.table import Table

    document = Document(path)
    output: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            rows = [
                [cell.text.replace("\n", " ").strip() for cell in row.cells] for row in block.rows
            ]
            if rows:
                output.extend(
                    [
                        "| " + " | ".join(rows[0]) + " |",
                        "| " + " | ".join("---" for _ in rows[0]) + " |",
                    ]
                )
                output.extend("| " + " | ".join(row) + " |" for row in rows[1:])
            continue
        paragraph = block
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name.lower() if paragraph.style else ""
        if style.startswith("heading"):
            match = re.search(r"(\d+)", style)
            output.append(f"{'#' * min(int(match.group(1)) if match else 1, 6)} {text}")
        elif style == "list bullet":
            output.append(f"- {text}")
        elif style == "list number":
            output.append(f"1. {text}")
        else:
            rendered = "".join(_docx_run(run) for run in paragraph.runs) or text
            output.append(rendered)
    title = document.core_properties.title or path.stem
    return ImportedText("\n\n".join(output) + "\n", title, "docx")


def _docx_run(run: object) -> str:
    text = getattr(run, "text", "")
    if getattr(run, "bold", False):
        text = f"**{text}**"
    if getattr(run, "italic", False):
        text = f"*{text}*"
    return text


def _read_epub(path: Path) -> ImportedText:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    title_meta = book.get_metadata("DC", "title")
    title = title_meta[0][0] if title_meta else path.stem
    chunks: list[str] = []
    report: dict[str, Any] = {
        "source_format": "epub",
        "spine_documents": 0,
        "paragraphs": 0,
        "headings": 0,
        "images": 0,
        "links": 0,
        "footnote_links": 0,
        "warnings": [],
    }
    spine_items = [book.get_item_with_id(item_id) for item_id, _ in book.spine]
    documents = [item for item in spine_items if item and item.get_type() == ebooklib.ITEM_DOCUMENT]
    if not documents:
        documents = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    for item in documents:
        report["spine_documents"] += 1
        soup = BeautifulSoup(item.get_content(), "html.parser")
        report["paragraphs"] += len(soup.find_all("p"))
        report["headings"] += len(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
        report["images"] += len(soup.find_all("img"))
        report["links"] += len(soup.find_all("a"))
        report["footnote_links"] += len(
            soup.select('a[epub\\:type~="noteref"], a[role="doc-noteref"], a.footnoteup')
        )
        chapter_number = ""
        for node in soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "li", "img"]
        ):
            text = " ".join(node.get_text(" ", strip=True).split())
            classes = set(node.get("class") or [])
            if node.name == "img":
                alt = node.get("alt", "").strip()
                chunks.append(f"![{alt}]({node.get('src', '')})")
                continue
            if not text:
                continue
            if "cn" in classes:
                chapter_number = text
                continue
            if "ct" in classes:
                chunks.append(f"# {' '.join(part for part in (chapter_number, text) if part)}")
                chapter_number = ""
                continue
            if node.name.startswith("h"):
                chunks.append(f"{'#' * int(node.name[1])} {text}")
            elif node.name == "blockquote":
                chunks.append(f"> {text}")
            elif node.name == "li":
                chunks.append(f"- {text}")
            else:
                chunks.append(_html_inline_to_markdown(node))
    if report["images"]:
        report["warnings"].append(
            "Images are preserved as Markdown references but binary assets are not copied yet"
        )
    if report["links"]:
        report["warnings"].append(
            "Links are preserved where they occur inside selected text blocks"
        )
    if report["footnote_links"]:
        report["warnings"].append("EPUB footnote backlinks require manual fidelity review")
    return ImportedText("\n\n".join(chunks) + "\n", title, "epub", report)


def _read_jats(path: Path) -> ImportedText:
    """Convert the review-relevant subset of a JATS article into Markdown.

    JATS is an XML interchange format used by publishers including PLOS and
    PubMed Central.  This importer deliberately keeps the publication objects
    visible rather than flattening them into prose: figures, tables, equations,
    citations, footnotes, and references all remain explicit in the normalized
    source and are counted in the import-loss report.  Binary graphics stay in
    the original artifact for now; the report makes that limitation explicit.
    """
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid XML source: {error}") from error
    if _local_name(root.tag) != "article":
        raise ValueError("XML import currently supports JATS article documents only")

    article_title = _jats_text(_first(root, ".//article-title")) or path.stem
    report: dict[str, Any] = {
        "source_format": "jats",
        "paragraphs": 0,
        "headings": 0,
        "figures": 0,
        "tables": 0,
        "equations": 0,
        "citations": 0,
        "footnotes": 0,
        "references": 0,
        "warnings": [],
    }
    output = [f"# {article_title}"]
    abstract = _first(root, ".//abstract")
    if abstract is not None:
        output.append("## Abstract")
        output.extend(_jats_paragraphs(abstract, report))

    body = _first(root, ".//body")
    if body is None:
        report["warnings"].append("JATS article has no body element")
    else:
        output.extend(_jats_body_blocks(body, report, level=1))

    notes = _first(root, ".//fn-group")
    if notes is not None:
        footnotes = [_jats_text(node) for node in _children(notes, "fn")]
        footnotes = [value for value in footnotes if value]
        if footnotes:
            output.append("## Footnotes")
            output.extend(f"[^fn-{index}]: {value}" for index, value in enumerate(footnotes, 1))
            report["footnotes"] = len(footnotes)

    references = _first(root, ".//ref-list")
    if references is not None:
        entries = [_jats_text(node) for node in _children(references, "ref")]
        entries = [value for value in entries if value]
        if entries:
            output.append("## References")
            output.extend(f"{index}. {entry}" for index, entry in enumerate(entries, 1))
            report["references"] = len(entries)

    if report["figures"]:
        report["warnings"].append(
            "JATS figure captions and labels are retained; graphic binaries require a publishing-stage asset fetch"
        )
    if report["equations"]:
        report["warnings"].append(
            "JATS equations are retained as protected source blocks and require a math-aware publishing renderer"
        )
    return ImportedText("\n\n".join(output).strip() + "\n", article_title, "jats", report)


def _jats_body_blocks(node: ElementTree.Element, report: dict[str, Any], level: int) -> list[str]:
    output: list[str] = []
    for child in list(node):
        name = _local_name(child.tag)
        if name == "sec":
            title = _jats_text(_first(child, "title"))
            if title:
                output.append(f"{'#' * min(level + 1, 6)} {title}")
                report["headings"] += 1
            output.extend(_jats_body_blocks(child, report, level + 1))
        elif name == "p":
            value = _jats_text(child)
            if value:
                output.append(value)
                report["paragraphs"] += 1
                report["citations"] += len(_descendants(child, "xref"))
        elif name == "fig":
            output.extend(_jats_figure(child, report))
        elif name == "table-wrap":
            output.extend(_jats_table(child, report))
        elif name in {"disp-formula", "formula"}:
            value = _jats_text(child)
            if value:
                output.append(f"```math\n{value}\n```")
                report["equations"] += 1
        elif name in {"list", "def-list"}:
            items = [_jats_text(item) for item in _descendants(child, "list-item")]
            items = [item for item in items if item]
            output.extend(f"- {item}" for item in items)
    return output


def _jats_paragraphs(node: ElementTree.Element, report: dict[str, Any]) -> list[str]:
    values = [_jats_text(item) for item in _children(node, "p")]
    values = [value for value in values if value]
    report["paragraphs"] += len(values)
    report["citations"] += sum(len(_descendants(item, "xref")) for item in _children(node, "p"))
    return values


def _jats_figure(node: ElementTree.Element, report: dict[str, Any]) -> list[str]:
    label = _jats_text(_first(node, "label")) or "Figure"
    caption = _jats_text(_first(node, "caption"))
    report["figures"] += 1
    return [f"> **{label}.** {caption}".rstrip()]


def _jats_table(node: ElementTree.Element, report: dict[str, Any]) -> list[str]:
    label = _jats_text(_first(node, "label")) or "Table"
    caption = _jats_text(_first(node, "caption"))
    table = _first(node, ".//table")
    report["tables"] += 1
    output = [f"> **{label}.** {caption}".rstrip()]
    if table is None:
        return output
    rows = []
    for row in _descendants(table, "tr"):
        cells = [_jats_text(cell) for cell in list(row) if _local_name(cell.tag) in {"td", "th"}]
        if cells:
            rows.append(cells)
    if rows:
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        markdown_rows = [
            "| " + " | ".join(normalized[0]) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
            *("| " + " | ".join(row) + " |" for row in normalized[1:]),
        ]
        output.append("\n".join(markdown_rows))
    return output


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in list(node) if _local_name(child.tag) == name]


def _descendants(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in node.iter() if child is not node and _local_name(child.tag) == name]


def _first(node: ElementTree.Element, path: str) -> ElementTree.Element | None:
    wanted = path.rsplit("/", 1)[-1].lstrip(".")
    for child in node.iter():
        if _local_name(child.tag) == wanted:
            return child
    return None


def _jats_text(node: ElementTree.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _html_inline_to_markdown(node: Any) -> str:
    """Render a small, auditable inline HTML subset as Markdown."""
    from bs4 import NavigableString, Tag

    def render(value: Any) -> str:
        if isinstance(value, NavigableString):
            return str(value)
        if not isinstance(value, Tag):
            return ""
        content = "".join(render(child) for child in value.children)
        if value.name in {"em", "i"}:
            return f"*{content}*"
        if value.name in {"strong", "b"}:
            return f"**{content}**"
        if value.name == "a":
            href = value.get("href", "")
            return f"[{content}]({href})" if href else content
        if value.name == "br":
            return "  \n"
        return content

    return html.unescape(" ".join(render(node).split()))
