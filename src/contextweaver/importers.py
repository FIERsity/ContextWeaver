"""Document importers normalize supported formats to reviewable Markdown."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportedText:
    markdown: str
    title: str
    source_format: str


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
    raise ValueError("Supported source formats: Markdown, TXT, DOCX, EPUB")


def _txt_to_markdown(text: str) -> str:
    return re.sub(r"(?im)^(chapter|part)\s+(.+)$", r"# \1 \2", text)


def _read_docx(path: Path) -> ImportedText:
    from docx import Document
    from docx.table import Table

    document = Document(path)
    output: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            rows = [[cell.text.replace("\n", " ").strip() for cell in row.cells] for row in block.rows]
            if rows:
                output.extend(["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"])
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
    spine_items = [book.get_item_with_id(item_id) for item_id, _ in book.spine]
    documents = [item for item in spine_items if item and item.get_type() == ebooklib.ITEM_DOCUMENT]
    if not documents:
        documents = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    for item in documents:
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "li"]):
            text = " ".join(node.get_text(" ", strip=True).split())
            if not text:
                continue
            if node.name.startswith("h"):
                chunks.append(f"{'#' * int(node.name[1])} {text}")
            elif node.name == "blockquote":
                chunks.append(f"> {text}")
            elif node.name == "li":
                chunks.append(f"- {text}")
            else:
                chunks.append(html.unescape(text))
    return ImportedText("\n\n".join(chunks) + "\n", title, "epub")
