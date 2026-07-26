"""Academic-paper PDF rendering with a deliberately small, inspectable surface."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .models import Section, SectionTitleRecord, Segment, SourceDocument, TranslationRecord
from .pipeline import STATE, active_section_titles, active_translations
from .storage import read_json, read_jsonl


def export_academic_pdf(root: Path, content: str = "translated") -> Path:
    """Write a reflowed A4 paper PDF; never attempt to reproduce source pagination.

    The renderer intentionally keeps figure/table placement near its source
    block.  It is a publication draft, not a claim of journal-template
    fidelity.  A complete active translation is required for translated and
    bilingual output, which prevents a partial run from looking final.
    """
    if content not in {"source", "translated", "bilingual"}:
        raise ValueError("content must be source, translated, or bilingual")
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as error:
        raise RuntimeError("Install ContextWeaver with the 'pdf' extra to render academic PDFs") from error

    source = SourceDocument(**read_json(root / STATE / "source_document.json"))
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(records)
    if content != "source" and set(active) != {item.id for item in segments}:
        raise RuntimeError("Academic PDF requires a complete translation; resume translate first")
    titles = active_section_titles(
        read_jsonl(root / STATE / "section_titles.jsonl", SectionTitleRecord)
    )

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("CWAcademicBody", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17, spaceAfter=6)
    source_style = ParagraphStyle("CWAcademicSource", parent=body, textColor=colors.HexColor("#555555"), fontSize=8.5, leading=13)
    title_style = ParagraphStyle("CWAcademicTitle", parent=styles["Title"], fontName="STSong-Light", fontSize=18, leading=26, alignment=TA_CENTER, spaceAfter=18)
    heading_style = ParagraphStyle("CWAcademicHeading", parent=styles["Heading2"], fontName="STSong-Light", fontSize=13, leading=19, spaceBefore=12, spaceAfter=7)
    caption_style = ParagraphStyle("CWAcademicCaption", parent=body, fontSize=9, leading=14, leftIndent=8, textColor=colors.HexColor("#333333"))
    output = root / "output" / "pdf" / f"{content}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=source.title,
        author="ContextWeaver",
    )
    story = [Paragraph(_escape(source.title), title_style)]
    by_section: dict[str, list[Segment]] = {}
    for item in segments:
        by_section.setdefault(item.section_id, []).append(item)
    for section in sections:
        section_segments = by_section.get(section.id, [])
        if not section_segments:
            continue
        target_title = titles.get(section.id).translated_title if section.id in titles else section.title
        heading = section.title if content == "source" else target_title
        story.append(Paragraph(_escape(heading), heading_style))
        if content == "bilingual" and target_title != section.title:
            story.append(Paragraph(_escape(section.title), source_style))
        for segment in section_segments:
            target = active[segment.id].translated_text if segment.id in active else segment.raw or segment.text
            if content == "source":
                _append_block(root, story, segment, segment.raw or segment.text, body, caption_style, Table, TableStyle, colors)
            elif content == "translated":
                _append_block(root, story, segment, target, body, caption_style, Table, TableStyle, colors)
            else:
                _append_block(root, story, segment, segment.raw or segment.text, source_style, caption_style, Table, TableStyle, colors)
                _append_block(root, story, segment, target, body, caption_style, Table, TableStyle, colors)
                story.append(Spacer(1, 5))
    document.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return output


def _append_block(
    root: Path,
    story: list[object],
    segment: Segment,
    value: str,
    body: object,
    caption: object,
    table_cls: object,
    table_style: object,
    colors: object,
) -> None:
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, Spacer

    image = re.fullmatch(r"!\[[^]]*\]\((assets/[^)]+)\)", value.strip())
    if image:
        path = root / "source" / image.group(1)
        if path.exists():
            picture = Image(str(path), width=150 * mm, height=100 * mm, kind="proportional")
            picture.hAlign = "CENTER"
            story.extend([picture, Spacer(1, 5)])
        return

    if segment.kind == "table":
        rows = _markdown_table(value)
        if rows:
            table = table_cls(rows, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                table_style(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("LEADING", (0, 0), (-1, -1), 11),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#777777")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.extend([table, Spacer(1, 8)])
            return
    style = caption if segment.kind == "blockquote" else body
    text = re.sub(r"^>\s*", "", value.strip()) if segment.kind == "blockquote" else value.strip()
    text = text.replace("**", "")
    text = re.sub(r"^```(?:math)?\s*|\s*```$", "", text)
    if text:
        story.append(Paragraph(_escape(text).replace("\n", "<br/>"), style))


def _markdown_table(value: str) -> list[list[str]]:
    lines = [line.strip() for line in value.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    rows = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index == 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append([_escape(cell) for cell in cells])
    return rows


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _page_number(canvas: object, document: object) -> None:
    canvas.saveState()
    canvas.setFont("STSong-Light", 8)
    canvas.drawCentredString(document.pagesize[0] / 2, 12 * 2.83465, str(document.page))
    canvas.restoreState()
