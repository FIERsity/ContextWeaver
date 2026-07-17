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
        target = translated[segment.id]
        if content == "translated":
            lines.extend([target, ""])
        else:
            lines.extend([f"> {segment.raw or segment.text}", "", target, "", "---", ""])
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
            target_html = renderer.render(_safe_epub_markdown(translated[segment.id]))
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
.source { color: #555; border-left: 0.2em solid #bbb; padding-left: 1em; }
.target { margin-bottom: 1.5em; }
pre, code { font-family: monospace; white-space: pre-wrap; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #999; padding: 0.35em; }
""".strip()
