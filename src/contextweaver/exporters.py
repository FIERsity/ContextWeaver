"""Output renderers for Markdown and EPUB translation artifacts."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from ebooklib import epub
from markdown_it import MarkdownIt

from .models import Project, Section, Segment


def render_markdown(
    sections: list[Section],
    segments: list[Segment],
    translated: dict[str, str],
    content: str,
    provenance: dict[str, str] | None = None,
    translated_titles: dict[str, str] | None = None,
) -> str:
    translated_titles = translated_titles or {}
    section_map = {section.id: section for section in sections}
    lines: list[str] = _markdown_provenance(provenance) if provenance else []
    previous = None
    for segment in segments:
        if segment.section_id != previous:
            section = section_map[segment.section_id]
            target_title = translated_titles.get(section.id, section.title)
            heading = (
                target_title
                if content == "translated" or target_title == section.title
                else f"{section.title} / {target_title}"
            )
            lines.extend([f"{'#' * section.level} {heading}", ""])
            previous = segment.section_id
        target = _reader_typography(translated[segment.id])
        if content == "translated":
            if _is_probable_subheading(segment):
                lines.extend([f"{'#' * min(section_map[segment.section_id].level + 1, 6)} {target}", ""])
            else:
                lines.extend([target, ""])
        else:
            target_block = (
                f"{'#' * min(section_map[segment.section_id].level + 1, 6)} {target}"
                if _is_probable_subheading(segment)
                else target
            )
            lines.extend([f"> {segment.raw or segment.text}", "", target_block, "", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_epub(
    path: Path,
    project: Project,
    sections: list[Section],
    segments: list[Segment],
    translated: dict[str, str],
    content: str,
    provenance: dict[str, str] | None = None,
    translated_titles: dict[str, str] | None = None,
) -> None:
    translated_titles = translated_titles or {}
    book = epub.EpubBook()
    suffix = "Bilingual" if content == "bilingual" else "Translation"
    book.set_identifier(f"{project.id}-{content}")
    display_title = provenance.get("title", project.name) if provenance else project.name
    book.set_title(f"{display_title} — {suffix}")
    book.set_language(project.target_language)
    if provenance:
        translator = provenance.get("translator")
        if translator:
            book.add_author(translator, file_as=translator, role="trl", uid="translator")
        if provenance.get("source_title"):
            book.add_metadata("DC", "source", provenance["source_title"])
        if provenance.get("reference_translation"):
            book.add_metadata(
                "DC",
                "contributor",
                provenance["reference_translation"],
                {"role": "translation-reference"},
            )
    css = epub.EpubItem(
        uid="style",
        file_name="style/contextweaver.css",
        media_type="text/css",
        content=_CSS.encode("utf-8"),
    )
    book.add_item(css)
    by_section: dict[str, list[Segment]] = {}
    for segment in segments:
        by_section.setdefault(segment.section_id, []).append(segment)
    chapters: list[epub.EpubHtml] = []
    if provenance:
        colophon = epub.EpubHtml(
            title="Translation provenance",
            file_name="translation-provenance.xhtml",
            lang=project.target_language,
        )
        colophon.content = _epub_provenance(provenance)
        colophon.add_item(css)
        book.add_item(colophon)
        chapters.append(colophon)
    renderer = MarkdownIt("commonmark", {"html": False})
    for section in sections:
        section_segments = by_section.get(section.id, [])
        if not section_segments:
            continue
        target_title = translated_titles.get(section.id, section.title)
        body = [f"<h1>{html.escape(target_title)}</h1>"]
        if content == "bilingual" and target_title != section.title:
            body.append(
                '<p class="source-title" lang="'
                + html.escape(project.source_language)
                + '">'
                + html.escape(section.title)
                + "</p>"
            )
        for segment in section_segments:
            target = _reader_typography(translated[segment.id])
            target_html = renderer.render(_safe_epub_markdown(target))
            if content == "bilingual":
                source_html = renderer.render(_safe_epub_markdown(segment.raw or segment.text))
                body.extend(
                    [
                        '<section class="source" lang="'
                        + html.escape(project.source_language)
                        + '">',
                        source_html,
                        "</section>",
                        '<section class="target">',
                        target_html,
                        "</section>",
                    ]
                )
            else:
                if _is_probable_subheading(segment):
                    body.append(f"<h2>{html.escape(target)}</h2>")
                else:
                    body.append(target_html)
        chapter = epub.EpubHtml(
            title=target_title,
            file_name=f"section-{section.ordinal:04d}.xhtml",
            lang=project.target_language,
        )
        chapter.content = "\n".join(body)
        chapter.add_item(css)
        book.add_item(chapter)
        chapters.append(chapter)
    if not chapters:
        raise RuntimeError("No non-empty sections available for EPUB export")
    book.toc = tuple(chapters)
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(path), book)


def _safe_epub_markdown(value: str) -> str:
    """Replace unresolved source images with explicit text placeholders."""
    return re.sub(
        r"!\[([^]]*)\]\([^)]+\)", lambda match: f"*[Image: {match.group(1) or 'unlabeled'}]*", value
    )


def _reader_typography(value: str) -> str:
    """Apply conservative zh-CN reader typography without changing stored records."""
    # Preserve literal code spans: a backtick is meaningful Markdown there and
    # must never be mistaken for quotation punctuation.
    parts = re.split(r"(`[^`\n]*`)", value)
    for index in range(0, len(parts), 2):
        parts[index] = _normalize_quote_marks(_restore_latin_apostrophes(parts[index]))
    return "".join(parts)


def _restore_latin_apostrophes(value: str) -> str:
    """Repair a common EPUB typography defect without touching Chinese quotes.

    Some EPUB producers serialize a Latin apostrophe as a right double quote,
    yielding reader-facing defects such as ``O”Reilly`` and ``Economists”
    Hour``.  The rule is deliberately confined to Latin-word contexts, so a
    Chinese closing quote (``“中文”``) remains a closing quote.
    """
    latin = r"A-Za-zÀ-ÖØ-öø-ÿ"
    value = re.sub(rf"(?<=[{latin}])[”’](?=[{latin}])", "'", value)
    return re.sub(rf"(?<=[{latin}])[”’](?=\s+[{latin}])", "'", value)


def _normalize_quote_marks(value: str) -> str:
    """Use Mainland Chinese outer quotes and single quotes for nesting.

    Imported reference drafts may contain Taiwan-style ``「…」`` quotation
    marks.  Reader artifacts normalize both those and curly single outer
    quotes to ``“…”`` while preserving meaningful nested quotations.
    """
    output: list[str] = []
    double_depth = 0
    for character in value:
        if character in {"“", "「"} and double_depth == 0:
            double_depth += 1
        elif character in {"”", "」"} and double_depth:
            double_depth -= 1
        if character == "『":
            output.append("‘")
            continue
        if character == "』":
            output.append("’")
            continue
        if character in {"‘", "「"} and double_depth == 0:
            output.append("“")
        elif character in {"’", "」"} and double_depth == 0:
            output.append("”")
        elif character == "「":
            output.append("“")
        elif character == "」":
            output.append("”")
        else:
            output.append(character)
    return "".join(output)


def _is_probable_subheading(segment: Segment) -> bool:
    """Recognize imported EPUB's CSS-only title paragraphs for reader output.

    The source EPUB does not expose these as heading tags.  This deliberately
    narrow heuristic avoids promoting ordinary prose, and never affects stored
    Segments or source alignment.
    """
    source = segment.text.strip()
    words = source.split()
    return (
        segment.kind == "paragraph"
        and source == (segment.raw or source).strip()
        and 1 < len(words) <= 8
        and len(source) <= 80
        and not re.search(r"[.!?;:]$", source)
        and all(word[:1].isupper() or word.casefold() in {"of", "the", "and", "in", "to"} for word in words)
    )


def _markdown_provenance(provenance: dict[str, str]) -> list[str]:
    lines = ["---"]
    for key in (
        "title",
        "source_title",
        "source_language",
        "target_language",
        "translator",
        "reference_translation",
        "fidelity_note",
    ):
        value = provenance.get(key)
        if value:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return [*lines, "---", ""]


def _epub_provenance(provenance: dict[str, str]) -> str:
    labels = {
        "source_title": "Source",
        "translator": "Translator",
        "reference_translation": "Translation reference",
        "fidelity_note": "Fidelity policy",
    }
    rows = [
        f"<dt>{html.escape(labels[key])}</dt><dd>{html.escape(provenance[key])}</dd>"
        for key in labels
        if provenance.get(key)
    ]
    return "<h1>Translation provenance</h1><dl>" + "".join(rows) + "</dl>"


_CSS = """
body { font-family: serif; line-height: 1.65; margin: 5%; }
h1 { line-height: 1.25; margin: 1.5em 0 1em; }
h2 { font-size: 1.18em; font-weight: 700; line-height: 1.35; margin: 2em 0 0.75em; }
.source { color: #555; border-left: 0.2em solid #bbb; padding-left: 1em; }
.target { margin-bottom: 1.5em; }
pre, code { font-family: monospace; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #999; padding: 0.35em; }
""".strip()
