"""Local human-translation references and conservative locale adaptation."""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opencc import OpenCC

from .importers import read_source
from .models import LocaleAdaptation, Project, ReferenceAlignment, Section, Segment, SourceDocument
from .pipeline import STATE, _parse, stable_id
from .storage import read_json, read_jsonl, write_json, write_jsonl

REFERENCE = "reference"


def import_reference(
    root: Path, source: Path, language: str, credit: str = ""
) -> tuple[int, int, int]:
    imported = read_source(source)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    directory = root / STATE / REFERENCE
    directory.mkdir(parents=True, exist_ok=True)
    original = directory / f"original{source.suffix.lower()}"
    if not original.exists():
        shutil.copyfile(source, original)
    normalized = directory / "document.md"
    normalized.write_text(imported.markdown, encoding="utf-8")
    document = SourceDocument(
        stable_id("ref", digest), stable_id("reference-project", root.resolve()), imported.title,
        str(normalized.relative_to(root)), "text/markdown", digest,
        str(original.relative_to(root)), imported.source_format,
    )
    sections, segments = _parse(document, imported.markdown)
    write_json(
        directory / "document.json",
        {**document.to_dict(), "language": language, "credit": credit},
    )
    write_jsonl(directory / "sections.jsonl", sections)
    write_jsonl(directory / "segments.jsonl", segments)
    if imported.report is not None:
        write_json(directory / "import_report.json", imported.report)
    alignments = align_reference(root, sections)
    return len(sections), len(segments), len(alignments)


def align_reference(root: Path, reference_sections: list[Section] | None = None) -> list[ReferenceAlignment]:
    source_sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    if not source_sections:
        raise RuntimeError("Segment the source before importing a reference translation")
    if reference_sections is None:
        reference_sections = read_jsonl(root / STATE / REFERENCE / "sections.jsonl", Section)
    source_by_key = {_chapter_key(item.title): item for item in source_sections if _chapter_key(item.title)}
    reference_by_key = {_chapter_key(item.title): item for item in reference_sections if _chapter_key(item.title)}
    alignments = [
        ReferenceAlignment(source_by_key[key].id, reference_by_key[key].id, key, 0.98)
        for key in sorted(source_by_key.keys() & reference_by_key.keys(), key=_chapter_sort)
    ]
    write_jsonl(root / STATE / REFERENCE / "alignments.jsonl", alignments)
    return alignments


def simplify_reference(root: Path) -> tuple[int, Path]:
    count, paths = simplify_reference_outputs(root, {"markdown"})
    return count, paths[0]


def simplify_reference_outputs(root: Path, formats: set[str]) -> tuple[int, list[Path]]:
    if not formats or not formats <= {"markdown", "epub"}:
        raise ValueError("Reference formats must be markdown and/or epub")
    directory = root / STATE / REFERENCE
    segments = read_jsonl(directory / "segments.jsonl", Segment)
    sections = read_jsonl(directory / "sections.jsonl", Section)
    if not segments:
        raise RuntimeError("No reference translation. Run reference-import first.")
    converter = OpenCC("tw2sp")
    records = [LocaleAdaptation(item.id, item.raw or item.text, converter.convert(item.raw or item.text), "opencc-tw2sp") for item in segments]
    write_jsonl(directory / "segments.zh-CN.jsonl", records)
    from .exporters import render_markdown, write_epub

    translated = {record.reference_segment_id: record.adapted_text for record in records}
    converted_sections = [replace(item, title=converter.convert(item.title)) for item in sections]
    project_data = read_json(root / "project.json")
    project = Project(**project_data)
    reference_project = replace(project, name=f"{project.name} — Mainland Chinese Reference", target_language="zh-CN")
    reference_data = read_json(directory / "document.json")
    credit = str(reference_data.get("credit", ""))
    provenance = {
        "title": reference_project.name,
        "source_title": str(reference_data.get("title", "Human translation reference")),
        "source_language": str(reference_data.get("language", "zh-TW")),
        "target_language": "zh-CN",
        "translator": "Locale adaptation by ContextWeaver OpenCC tw2sp (not a new translation)",
        "reference_translation": credit,
        "fidelity_note": "Draft regional-script adaptation of the credited human translation; not a translation from the original source.",
    }
    paths: list[Path] = []
    if "markdown" in formats:
        path = root / "output" / "reference-zh-CN.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_markdown(converted_sections, segments, translated, "translated", provenance),
            encoding="utf-8",
        )
        paths.append(path)
    if "epub" in formats:
        path = root / "output" / "reference-zh-CN.epub"
        write_epub(
            path, reference_project, converted_sections, segments, translated,
            "translated", provenance,
        )
        paths.append(path)
    return len(records), paths


def reference_context(root: Path, source_segments: list[Segment]) -> list[str]:
    """Return a small proportional window from the aligned human translation."""
    if not source_segments:
        return []
    directory = root / STATE / REFERENCE
    paths = [
        root / STATE / "segments.jsonl", directory / "sections.jsonl",
        directory / "segments.jsonl", directory / "alignments.jsonl",
        directory / "segments.zh-CN.jsonl",
    ]
    stamps = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)
    source_by_section, reference_by_source, adaptations = _reference_index(str(root.resolve()), stamps)
    source_all = source_by_section.get(source_segments[0].section_id, [])
    reference_all = reference_by_source.get(source_segments[0].section_id, [])
    if not source_all or not reference_all:
        return []
    position = source_all.index(source_segments[0]) / max(1, len(source_all) - 1)
    center = round(position * max(0, len(reference_all) - 1))
    return [
        adaptations.get(item.id, item.raw or item.text)
        for item in reference_all[max(0, center - 1) : center + 2]
    ]


@lru_cache(maxsize=8)
def _reference_index(
    root_text: str, stamps: tuple[int, ...]
) -> tuple[dict[str, list[Segment]], dict[str, list[Segment]], dict[str, str]]:
    del stamps  # Included in the cache key to invalidate on file changes.
    root = Path(root_text)
    directory = root / STATE / REFERENCE
    source_segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    reference_sections = read_jsonl(directory / "sections.jsonl", Section)
    reference_segments = read_jsonl(directory / "segments.jsonl", Segment)
    alignments = read_jsonl(directory / "alignments.jsonl", ReferenceAlignment)
    source_by_section: dict[str, list[Segment]] = {}
    for segment in source_segments:
        source_by_section.setdefault(segment.section_id, []).append(segment)
    section_ordinals = {item.id: item.ordinal for item in reference_sections}
    reference_by_source: dict[str, list[Segment]] = {}
    for alignment in alignments:
        start = section_ordinals[alignment.reference_section_id]
        later = [
            section_ordinals[item.reference_section_id]
            for item in alignments
            if section_ordinals[item.reference_section_id] > start
        ]
        end = min(later) if later else len(reference_sections)
        included = {item.id for item in reference_sections if start <= item.ordinal < end}
        reference_by_source[alignment.source_section_id] = [
            item for item in reference_segments if item.section_id in included
        ]
    adaptations = {
        item.reference_segment_id: item.adapted_text
        for item in read_jsonl(directory / "segments.zh-CN.jsonl", LocaleAdaptation)
    }
    return source_by_section, reference_by_source, adaptations


def _chapter_key(title: str) -> str | None:
    value = unicodedata.normalize("NFKC", title).strip().casefold()
    if re.search(r"\b(prologue|preface)\b", value) or value.startswith("序言"):
        return "chapter-0"
    match = re.match(r"^(?:chapter\s*)?(\d{1,2})\b", value)
    return f"chapter-{int(match.group(1))}" if match else None


def _chapter_sort(key: str) -> int:
    return int(key.rsplit("-", 1)[1])
