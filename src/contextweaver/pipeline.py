"""Idempotent pipeline operations, independent from CLI presentation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .adapters import TranslationAdapter
from .importers import read_source
from .markdown import parse_markdown
from .models import (
    ContextPacket,
    Entity,
    GlossaryEntry,
    Manifest,
    Project,
    ReviewIssue,
    Section,
    Segment,
    SourceDocument,
    TranslationRecord,
    TranslationUnit,
)
from .storage import append_jsonl, read_json, read_jsonl, write_json, write_jsonl

STATE = "state"


def stable_id(prefix: str, *parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def normalize(text: str) -> str:
    return " ".join(text.split())


def init_project(root: Path, name: str, source_language: str, target_language: str) -> Project:
    root = root.resolve()
    config = root / "project.json"
    if config.exists():
        raise FileExistsError(f"Project already exists: {config}")
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("source", STATE, "output", "notes"):
        (root / directory).mkdir()
    project = Project(
        stable_id("prj", name, source_language, target_language),
        name,
        source_language,
        target_language,
        2,
    )
    write_json(config, project)
    write_json(root / STATE / "manifest.json", _manifest(project.id))
    (root / STATE / "glossary.csv").write_text(
        "term,preferred_translation,allowed_variants,note,source_segment_id,confidence,evidence_segment_ids,status\n",
        encoding="utf-8",
    )
    write_jsonl(root / STATE / "entities.jsonl", [])
    return project


def import_document(root: Path, source: Path) -> SourceDocument:
    project = _project(root)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    imported = read_source(source)
    destination = root / "source" / "document.md"
    original = root / "source" / f"original{source.suffix.lower()}"
    existing = _source_document(root)
    if existing and existing.sha256 != digest:
        raise FileExistsError("A different source is already imported; use --replace explicitly")
    if not original.exists():
        shutil.copyfile(source, original)
    destination.write_text(imported.markdown, encoding="utf-8")
    document = SourceDocument(
        stable_id("doc", project.id, digest),
        project.id,
        imported.title,
        str(destination.relative_to(root)),
        "text/markdown",
        digest,
        str(original.relative_to(root)),
        imported.source_format,
    )
    write_json(root / STATE / "source_document.json", document)
    if imported.report is not None:
        write_json(root / STATE / "import_report.json", imported.report)
    _update_manifest(root, source_sha256=digest, steps={"import": "completed"})
    return document


def replace_document(root: Path, source: Path) -> SourceDocument:
    read_source(source)  # Validate before removing existing project state.
    for name in (
        "source_document.json",
        "sections.jsonl",
        "segments.jsonl",
        "units.jsonl",
        "translations.jsonl",
        "reviews.jsonl",
        "scope_reviews.jsonl",
        "issues.jsonl",
        "translation_brief.json",
        "section_summaries.jsonl",
        "ambiguities.jsonl",
    ):
        (root / STATE / name).unlink(missing_ok=True)
    (root / "notes" / "translation_brief.md").unlink(missing_ok=True)
    (root / "notes" / "section_summaries.md").unlink(missing_ok=True)
    for old in (root / "source").glob("document.*"):
        old.unlink()
    return import_document(root, source)


def segment_document(
    root: Path, unit_size: int = 3
) -> tuple[list[Section], list[Segment], list[TranslationUnit]]:
    if unit_size < 1:
        raise ValueError("unit_size must be at least 1")
    document = _require_source(root)
    text = (root / document.source_path).read_text(encoding="utf-8")
    sections, segments = _parse(document, text)
    units: list[TranslationUnit] = []
    by_section: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        by_section[segment.section_id].append(segment)
    for section in sections:
        for offset in range(0, len(by_section[section.id]), unit_size):
            batch = by_section[section.id][offset : offset + unit_size]
            units.append(
                TranslationUnit(
                    stable_id("unit", section.id, *(item.id for item in batch)),
                    section.id,
                    [item.id for item in batch],
                    len(units),
                )
            )
    write_jsonl(root / STATE / "sections.jsonl", sections)
    write_jsonl(root / STATE / "segments.jsonl", segments)
    write_jsonl(root / STATE / "units.jsonl", units)
    _update_manifest(
        root,
        section_count=len(sections),
        segment_count=len(segments),
        unit_count=len(units),
        steps={"segment": "completed"},
    )
    return sections, segments, units


def build_context(root: Path, unit: TranslationUnit) -> ContextPacket:
    paths = [
        root / STATE / "segments.jsonl",
        root / STATE / "glossary.csv",
        root / STATE / "entities.jsonl",
    ]
    stamps = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)
    segments, index, glossary, entities = _context_index(str(root.resolve()), stamps)
    selected = [segments[index[item]] for item in unit.segment_ids]
    first, last = index[selected[0].id], index[selected[-1].id]
    from .reference import reference_context

    project = _project(root)
    brief_path = root / STATE / "translation_brief.json"
    strategy = read_json(brief_path) if brief_path.exists() else {}

    return ContextPacket(
        unit.id,
        selected,
        segments[first - 1].text if first else None,
        segments[last + 1].text if last + 1 < len(segments) else None,
        _section_summary(root, unit.section_id),
        glossary,
        entities,
        reference_context(root, selected),
        project.source_language,
        project.target_language,
        strategy,
    )


@lru_cache(maxsize=16)
def _context_index(
    root_text: str, stamps: tuple[int, ...]
) -> tuple[list[Segment], dict[str, int], list[GlossaryEntry], list[Entity]]:
    del stamps
    root = Path(root_text)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    return (
        segments,
        {segment.id: position for position, segment in enumerate(segments)},
        _glossary(root),
        read_jsonl(root / STATE / "entities.jsonl", Entity),
    )


def translate_project(
    root: Path,
    adapter: TranslationAdapter,
    segment_ids: set[str] | None = None,
    section_ids: set[str] | None = None,
    term: str | None = None,
    reason: str = "initial",
    max_units: int | None = None,
) -> tuple[int, int]:
    if max_units is not None and max_units < 1:
        raise ValueError("max_units must be at least 1")
    units = read_jsonl(root / STATE / "units.jsonl", TranslationUnit)
    if not units:
        raise RuntimeError("No translation units. Run segment first.")
    existing = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(existing)
    selected = _selected_segments(root, segment_ids, section_ids, term)
    retranslate = any(value for value in (segment_ids, section_ids, term))
    written = skipped = processed_units = 0
    for unit in units:
        packet = build_context(root, unit)
        candidates = [
            segment
            for segment in packet.source_segments
            if selected is None or segment.id in selected
        ]
        pending = [segment for segment in candidates if retranslate or segment.id not in active]
        if not pending:
            skipped += len(candidates)
            continue
        if max_units is not None and processed_units >= max_units:
            break
        pending_packet = ContextPacket(
            unit.id,
            pending,
            packet.previous_text,
            packet.next_text,
            packet.section_summary,
            packet.glossary,
            packet.entities,
            packet.reference_texts,
            packet.source_language,
            packet.target_language,
            packet.translation_strategy,
        )
        outputs = adapter.translate(pending_packet)
        if len(outputs) != len(pending):
            raise RuntimeError(
                f"Adapter returned {len(outputs)} outputs for {len(pending)} segments"
            )
        for segment, output in zip(pending, outputs, strict=True):
            if not output.strip():
                raise RuntimeError(f"Adapter returned empty translation for {segment.id}")
            previous = active.get(segment.id)
            revision = previous.revision + 1 if previous else 1
            record = TranslationRecord(
                stable_id("tr", unit.id, segment.id, adapter.name, adapter.model, revision),
                unit.id,
                segment.id,
                output,
                adapter.name,
                adapter.model,
                "translate-v3-source-faithful-natural-zh",
                datetime.now(timezone.utc).isoformat(),
                hashlib.sha256(segment.text.encode()).hexdigest(),
                "completed",
                revision,
                previous.id if previous else None,
                reason,
            )
            append_jsonl(root / STATE / "translations.jsonl", record)
            active[segment.id] = record
            written += 1
        processed_units += 1
    total_segments = len(read_jsonl(root / STATE / "segments.jsonl", Segment))
    translation_status = "completed" if len(active) == total_segments else "pending"
    _update_manifest(root, translation_count=len(active), steps={"translate": translation_status})
    return written, skipped


def validate_project(
    root: Path,
    section_ids: set[str] | None = None,
    segment_ids: set[str] | None = None,
) -> list[ReviewIssue]:
    all_segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    segments = [
        item
        for item in all_segments
        if (section_ids is None or item.section_id in section_ids)
        and (segment_ids is None or item.id in segment_ids)
    ]
    if section_ids:
        unknown = section_ids - {item.section_id for item in all_segments}
        if unknown:
            raise ValueError(f"Unknown section IDs: {sorted(unknown)}")
    if segment_ids:
        unknown_segments = segment_ids - {item.id for item in all_segments}
        if unknown_segments:
            raise ValueError(f"Unknown segment IDs: {sorted(unknown_segments)}")
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    source_ids = {item.id for item in segments}
    active = active_translations(records)
    counts = {segment_id: 1 for segment_id in active}
    issues: list[ReviewIssue] = []
    for segment in segments:
        if counts.get(segment.id, 0) == 0:
            issues.append(
                _issue("missing_translation", "No completed translation", segment.id, "error")
            )
    if section_ids is None and segment_ids is None:
        for segment_id in counts.keys() - source_ids:
            issues.append(
                _issue(
                    "orphan_translation", "Translation has no source segment", segment_id, "error"
                )
            )
    from .validation import quality_issues

    issues.extend(quality_issues(segments, records, _glossary(root)))
    if section_ids or segment_ids:
        scope_ids = sorted((section_ids or set()) | (segment_ids or set()))
        scope = scope_ids[0] if len(scope_ids) == 1 else stable_id("scope", *scope_ids)
        write_jsonl(root / STATE / "issues" / f"{scope}.jsonl", issues)
    else:
        write_jsonl(root / STATE / "issues.jsonl", issues)
        _update_manifest(root, steps={"validate": "completed" if not issues else "needs_review"})
    return issues


def export_project(root: Path) -> tuple[Path, Path]:
    paths = export_selected(root, {"markdown"}, {"translated", "bilingual"})
    return paths[0], paths[1]


def export_selected(
    root: Path,
    formats: set[str],
    contents: set[str],
    translator: str | None = None,
    reference_credit: str | None = None,
    section_ids: set[str] | None = None,
    segment_ids: set[str] | None = None,
) -> list[Path]:
    valid_formats = {"markdown", "epub"}
    valid_contents = {"translated", "bilingual"}
    if not formats or not formats <= valid_formats:
        raise ValueError(f"formats must be selected from {sorted(valid_formats)}")
    if not contents or not contents <= valid_contents:
        raise ValueError(f"contents must be selected from {sorted(valid_contents)}")
    issues = validate_project(root, section_ids, segment_ids)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise RuntimeError(f"Export blocked by {len(errors)} validation error(s)")
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    if section_ids:
        sections = [item for item in sections if item.id in section_ids]
        segments = [item for item in segments if item.section_id in section_ids]
    if segment_ids:
        segments = [item for item in segments if item.id in segment_ids]
        included_sections = {item.section_id for item in segments}
        sections = [item for item in sections if item.id in included_sections]
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(records)
    translated = {segment_id: item.translated_text for segment_id, item in active.items()}
    from .exporters import render_markdown, write_epub

    project = _project(root)
    source = _require_source(root)
    inferred_translator = _translator_attribution(list(active.values()))
    provenance = {
        "title": project.name,
        "source_title": source.title,
        "source_language": project.source_language,
        "target_language": project.target_language,
        "translator": translator or inferred_translator,
        "reference_translation": reference_credit or _reference_credit(root),
        "fidelity_note": "The source-language document is authoritative. Human translations are consultation references only.",
    }
    write_json(root / STATE / "export_metadata.json", provenance)
    output_root = root / "output"
    if section_ids or segment_ids:
        scope_ids = sorted((section_ids or set()) | (segment_ids or set()))
        scope = scope_ids[0] if len(scope_ids) == 1 else stable_id("scope", *scope_ids)
        output_root = output_root / "sections" / scope
    paths: list[Path] = []
    for content in ("translated", "bilingual"):
        if content not in contents:
            continue
        if "markdown" in formats:
            path = output_root / f"{content}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                render_markdown(sections, segments, translated, content, provenance),
                encoding="utf-8",
            )
            paths.append(path)
        if "epub" in formats:
            path = output_root / f"{content}.epub"
            write_epub(path, project, sections, segments, translated, content, provenance)
            paths.append(path)
    if section_ids is None and segment_ids is None:
        _update_manifest(root, steps={"export": "completed"})
    return paths


def import_translation_draft(
    root: Path,
    draft: Path,
    adapter: str,
    model: str,
    reason: str,
) -> int:
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    units = read_jsonl(root / STATE / "units.jsonl", TranslationUnit)
    segment_map = {item.id: item for item in segments}
    unit_by_segment = {segment_id: unit for unit in units for segment_id in unit.segment_ids}
    existing = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(existing)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(draft.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if set(raw) != {"segment_id", "translated_text"}:
            raise ValueError(f"{draft}:{line_number}: expected segment_id and translated_text only")
        segment_id = str(raw["segment_id"])
        text = str(raw["translated_text"])
        if segment_id not in segment_map:
            raise ValueError(f"{draft}:{line_number}: unknown segment ID {segment_id}")
        if segment_id in seen:
            raise ValueError(f"{draft}:{line_number}: duplicate segment ID {segment_id}")
        if not text.strip():
            raise ValueError(f"{draft}:{line_number}: empty translation")
        seen.add(segment_id)
        rows.append({"segment_id": segment_id, "translated_text": text})
    for row in rows:
        segment = segment_map[row["segment_id"]]
        unit = unit_by_segment[segment.id]
        previous = active.get(segment.id)
        revision = previous.revision + 1 if previous else 1
        record = TranslationRecord(
            stable_id("tr", unit.id, segment.id, adapter, model, revision),
            unit.id,
            segment.id,
            row["translated_text"],
            adapter,
            model,
            "translate-v3-source-faithful-natural-zh",
            datetime.now(timezone.utc).isoformat(),
            hashlib.sha256(segment.text.encode()).hexdigest(),
            "completed",
            revision,
            previous.id if previous else None,
            reason,
        )
        append_jsonl(root / STATE / "translations.jsonl", record)
        active[segment.id] = record
    total_segments = len(segments)
    translation_status = "completed" if len(active) == total_segments else "pending"
    _update_manifest(root, translation_count=len(active), steps={"translate": translation_status})
    return len(rows)


def project_status(root: Path) -> Manifest:
    path = root / STATE / "manifest.json"
    data = read_json(path)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    if segments:
        count = len(active_translations(records))
        data["translation_count"] = count
        data["steps"]["translate"] = "completed" if count == len(segments) else "pending"
        if count != len(segments):
            data["steps"]["export"] = "pending"
    write_json(path, data)
    return Manifest(**data)


def migrate_project(root: Path) -> int:
    """Upgrade transparent v1 records to schema v2 without changing IDs."""
    project_path = root / "project.json"
    project = read_json(project_path)
    version = int(project.get("schema_version", 1))
    if version >= 2:
        return version
    document_path = root / STATE / "source_document.json"
    if document_path.exists():
        document = read_json(document_path)
        document.setdefault("original_path", document.get("source_path"))
        document.setdefault(
            "source_format", Path(document["source_path"]).suffix.lstrip(".") or "markdown"
        )
        write_json(document_path, document)
    segments_path = root / STATE / "segments.jsonl"
    if segments_path.exists():
        write_jsonl(segments_path, read_jsonl(segments_path, Segment))
    translations_path = root / STATE / "translations.jsonl"
    if translations_path.exists():
        write_jsonl(translations_path, read_jsonl(translations_path, TranslationRecord))
    project["schema_version"] = 2
    write_json(project_path, project)
    manifest_path = root / STATE / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["schema_version"] = 2
    write_json(manifest_path, manifest)
    return 2


def _parse(document: SourceDocument, text: str) -> tuple[list[Section], list[Segment]]:
    blocks = parse_markdown(text)
    sections: list[Section] = []
    segments: list[Segment] = []
    current: Section | None = None
    ordinal = 0
    for block in blocks:
        if block.kind == "heading":
            title = block.title
            level = block.level
            current = Section(
                stable_id("sec", document.id, len(sections), title),
                document.id,
                title,
                level,
                len(sections),
            )
            sections.append(current)
            continue
        if current is None:
            current = Section(
                stable_id("sec", document.id, 0, document.title), document.id, document.title, 1, 0
            )
            sections.append(current)
        cleaned = normalize(block.text)
        if cleaned:
            segments.append(
                Segment(
                    stable_id("seg", document.id, current.id, ordinal, cleaned),
                    document.id,
                    current.id,
                    ordinal,
                    cleaned,
                    block.kind,
                    block.raw,
                    list(block.format_signature),
                    block.source_locator,
                )
            )
            ordinal += 1
    return sections, segments


def _glossary(root: Path) -> list[GlossaryEntry]:
    path = root / STATE / "glossary.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            GlossaryEntry(
                row["term"],
                row["preferred_translation"],
                [item.strip() for item in row["allowed_variants"].split("|") if item.strip()],
                row["note"],
                row["source_segment_id"] or None,
                float(row["confidence"] or 1),
                [item for item in row.get("evidence_segment_ids", "").split("|") if item],
                row.get("status", "approved") or "approved",
            )
            for row in csv.DictReader(handle)
            if row["term"]
        ]


def _section_summary(root: Path, section_id: str) -> str | None:
    from .models import SectionSummary
    from .summaries import active_section_summaries

    records = read_jsonl(root / STATE / "section_summaries.jsonl", SectionSummary)
    summary = active_section_summaries(records).get(section_id)
    return summary.summary if summary else None


def _project(root: Path) -> Project:
    path = root / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"Not a ContextWeaver project: {root}")
    return Project(**read_json(path))


def _source_document(root: Path) -> SourceDocument | None:
    path = root / STATE / "source_document.json"
    return SourceDocument(**read_json(path)) if path.exists() else None


def _require_source(root: Path) -> SourceDocument:
    source = _source_document(root)
    if source is None:
        raise RuntimeError("No source document. Run import first.")
    return source


def _manifest(project_id: str) -> Manifest:
    return Manifest(
        2,
        project_id,
        None,
        0,
        0,
        0,
        0,
        {
            "import": "pending",
            "segment": "pending",
            "translate": "pending",
            "validate": "pending",
            "export": "pending",
        },
    )


def _update_manifest(root: Path, **changes: object) -> None:
    path = root / STATE / "manifest.json"
    data = read_json(path)
    steps = changes.pop("steps", None)
    data.update(changes)
    if steps:
        data["steps"].update(steps)
    write_json(path, data)


def _issue(kind: str, message: str, segment_id: str, severity: str) -> ReviewIssue:
    return ReviewIssue(
        stable_id("issue", kind, segment_id, message), kind, message, segment_id, severity
    )  # type: ignore[arg-type]


def active_translations(records: list[TranslationRecord]) -> dict[str, TranslationRecord]:
    active: dict[str, TranslationRecord] = {}
    for record in records:
        if record.status == "completed" and (
            record.segment_id not in active or record.revision > active[record.segment_id].revision
        ):
            active[record.segment_id] = record
    return active


def _translator_attribution(records: list[TranslationRecord]) -> str:
    signatures = sorted({(item.adapter, item.model) for item in records})
    if not signatures:
        raise RuntimeError("Cannot attribute an export without completed TranslationRecords")
    if signatures == [("mock", "deterministic-copy-v1")]:
        return "ContextWeaver Mock Adapter (workflow test; not a final translation)"
    return "; ".join(
        f"ContextWeaver Agent using {adapter}/{model}" for adapter, model in signatures
    )


def _reference_credit(root: Path) -> str:
    path = root / STATE / "reference" / "document.json"
    if not path.exists():
        return ""
    data = read_json(path)
    return str(data.get("credit", ""))


def _selected_segments(
    root: Path, segment_ids: set[str] | None, section_ids: set[str] | None, term: str | None
) -> set[str] | None:
    if not any((segment_ids, section_ids, term)):
        return None
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    selected = set(segment_ids or set())
    if section_ids:
        selected.update(item.id for item in segments if item.section_id in section_ids)
    if term:
        selected.update(item.id for item in segments if term.casefold() in item.text.casefold())
    unknown = (segment_ids or set()) - {item.id for item in segments}
    if unknown:
        raise ValueError(f"Unknown segment IDs: {sorted(unknown)}")
    return selected
