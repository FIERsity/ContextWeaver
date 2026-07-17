"""Idempotent pipeline operations, independent from CLI presentation."""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections import defaultdict
from datetime import datetime, timezone
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
    project = Project(stable_id("prj", name, source_language, target_language), name, source_language, target_language, 2)
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
        stable_id("doc", project.id, digest), project.id, imported.title, str(destination.relative_to(root)),
        "text/markdown", digest, str(original.relative_to(root)), imported.source_format,
    )
    write_json(root / STATE / "source_document.json", document)
    _update_manifest(root, source_sha256=digest, steps={"import": "completed"})
    return document


def replace_document(root: Path, source: Path) -> SourceDocument:
    read_source(source)  # Validate before removing existing project state.
    for name in ("source_document.json", "sections.jsonl", "segments.jsonl", "units.jsonl", "translations.jsonl", "issues.jsonl"):
        (root / STATE / name).unlink(missing_ok=True)
    for old in (root / "source").glob("document.*"):
        old.unlink()
    return import_document(root, source)


def segment_document(root: Path, unit_size: int = 3) -> tuple[list[Section], list[Segment], list[TranslationUnit]]:
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
            units.append(TranslationUnit(
                stable_id("unit", section.id, *(item.id for item in batch)), section.id,
                [item.id for item in batch], len(units),
            ))
    write_jsonl(root / STATE / "sections.jsonl", sections)
    write_jsonl(root / STATE / "segments.jsonl", segments)
    write_jsonl(root / STATE / "units.jsonl", units)
    _update_manifest(root, section_count=len(sections), segment_count=len(segments), unit_count=len(units), steps={"segment": "completed"})
    return sections, segments, units


def build_context(root: Path, unit: TranslationUnit) -> ContextPacket:
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    index = {segment.id: position for position, segment in enumerate(segments)}
    selected = [segments[index[item]] for item in unit.segment_ids]
    first, last = index[selected[0].id], index[selected[-1].id]
    return ContextPacket(
        unit.id, selected, segments[first - 1].text if first else None,
        segments[last + 1].text if last + 1 < len(segments) else None,
        _section_summary(root, unit.section_id), _glossary(root),
        read_jsonl(root / STATE / "entities.jsonl", Entity),
    )


def translate_project(
    root: Path,
    adapter: TranslationAdapter,
    segment_ids: set[str] | None = None,
    section_ids: set[str] | None = None,
    term: str | None = None,
    reason: str = "initial",
) -> tuple[int, int]:
    units = read_jsonl(root / STATE / "units.jsonl", TranslationUnit)
    if not units:
        raise RuntimeError("No translation units. Run segment first.")
    existing = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(existing)
    selected = _selected_segments(root, segment_ids, section_ids, term)
    retranslate = any(value for value in (segment_ids, section_ids, term))
    written = skipped = 0
    for unit in units:
        packet = build_context(root, unit)
        candidates = [segment for segment in packet.source_segments if selected is None or segment.id in selected]
        pending = [segment for segment in candidates if retranslate or segment.id not in active]
        if not pending:
            skipped += len(candidates)
            continue
        pending_packet = ContextPacket(unit.id, pending, packet.previous_text, packet.next_text, packet.section_summary, packet.glossary, packet.entities)
        outputs = adapter.translate(pending_packet)
        if len(outputs) != len(pending):
            raise RuntimeError(f"Adapter returned {len(outputs)} outputs for {len(pending)} segments")
        for segment, output in zip(pending, outputs, strict=True):
            if not output.strip():
                raise RuntimeError(f"Adapter returned empty translation for {segment.id}")
            previous = active.get(segment.id)
            revision = previous.revision + 1 if previous else 1
            record = TranslationRecord(
                stable_id("tr", unit.id, segment.id, adapter.name, adapter.model, revision), unit.id, segment.id,
                output, adapter.name, adapter.model, "translate-v1", datetime.now(timezone.utc).isoformat(),
                hashlib.sha256(segment.text.encode()).hexdigest(), "completed", revision,
                previous.id if previous else None, reason,
            )
            append_jsonl(root / STATE / "translations.jsonl", record)
            active[segment.id] = record
            written += 1
    _update_manifest(root, translation_count=len(active), steps={"translate": "completed"})
    return written, skipped


def validate_project(root: Path) -> list[ReviewIssue]:
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    source_ids = {item.id for item in segments}
    active = active_translations(records)
    counts = {segment_id: 1 for segment_id in active}
    issues: list[ReviewIssue] = []
    for segment in segments:
        if counts.get(segment.id, 0) == 0:
            issues.append(_issue("missing_translation", "No completed translation", segment.id, "error"))
    for segment_id in counts.keys() - source_ids:
        issues.append(_issue("orphan_translation", "Translation has no source segment", segment_id, "error"))
    from .validation import quality_issues

    issues.extend(quality_issues(segments, records, _glossary(root)))
    write_jsonl(root / STATE / "issues.jsonl", issues)
    _update_manifest(root, steps={"validate": "completed" if not issues else "needs_review"})
    return issues


def export_project(root: Path) -> tuple[Path, Path]:
    issues = validate_project(root)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise RuntimeError(f"Export blocked by {len(errors)} validation error(s)")
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    translated = {segment_id: item.translated_text for segment_id, item in active_translations(records).items()}
    section_map = {section.id: section for section in sections}
    translated_lines: list[str] = []
    bilingual_lines: list[str] = []
    previous = None
    for segment in segments:
        if segment.section_id != previous:
            title = section_map[segment.section_id].title
            heading = "#" * section_map[segment.section_id].level
            translated_lines.extend([f"{heading} {title}", ""])
            bilingual_lines.extend([f"{heading} {title}", ""])
            previous = segment.section_id
        translated_lines.extend([translated[segment.id], ""])
        bilingual_lines.extend([f"> {segment.text}", "", translated[segment.id], "", "---", ""])
    translated_path = root / "output" / "translated.md"
    bilingual_path = root / "output" / "bilingual.md"
    translated_path.write_text("\n".join(translated_lines).rstrip() + "\n", encoding="utf-8")
    bilingual_path.write_text("\n".join(bilingual_lines).rstrip() + "\n", encoding="utf-8")
    _update_manifest(root, steps={"export": "completed"})
    return translated_path, bilingual_path


def project_status(root: Path) -> Manifest:
    return Manifest(**read_json(root / STATE / "manifest.json"))


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
        document.setdefault("source_format", Path(document["source_path"]).suffix.lstrip(".") or "markdown")
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
            current = Section(stable_id("sec", document.id, len(sections), title), document.id, title, level, len(sections))
            sections.append(current)
            continue
        if current is None:
            current = Section(stable_id("sec", document.id, 0, document.title), document.id, document.title, 1, 0)
            sections.append(current)
        cleaned = normalize(block.text)
        if cleaned:
            segments.append(Segment(stable_id("seg", document.id, current.id, ordinal, cleaned), document.id, current.id, ordinal, cleaned, block.kind, block.raw, list(block.format_signature), block.source_locator))
            ordinal += 1
    return sections, segments


def _glossary(root: Path) -> list[GlossaryEntry]:
    path = root / STATE / "glossary.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [GlossaryEntry(
            row["term"], row["preferred_translation"],
            [item.strip() for item in row["allowed_variants"].split("|") if item.strip()],
            row["note"], row["source_segment_id"] or None, float(row["confidence"] or 1),
            [item for item in row.get("evidence_segment_ids", "").split("|") if item],
            row.get("status", "approved") or "approved",
        ) for row in csv.DictReader(handle) if row["term"]]


def _section_summary(root: Path, section_id: str) -> str | None:
    path = root / STATE / "section_summaries.json"
    return read_json(path).get(section_id) if path.exists() else None


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
    return Manifest(2, project_id, None, 0, 0, 0, 0, {
        "import": "pending", "segment": "pending", "translate": "pending", "validate": "pending", "export": "pending",
    })


def _update_manifest(root: Path, **changes: object) -> None:
    path = root / STATE / "manifest.json"
    data = read_json(path)
    steps = changes.pop("steps", None)
    data.update(changes)
    if steps:
        data["steps"].update(steps)
    write_json(path, data)


def _issue(kind: str, message: str, segment_id: str, severity: str) -> ReviewIssue:
    return ReviewIssue(stable_id("issue", kind, segment_id, message), kind, message, segment_id, severity)  # type: ignore[arg-type]


def active_translations(records: list[TranslationRecord]) -> dict[str, TranslationRecord]:
    active: dict[str, TranslationRecord] = {}
    for record in records:
        if record.status == "completed" and (record.segment_id not in active or record.revision > active[record.segment_id].revision):
            active[record.segment_id] = record
    return active


def _selected_segments(root: Path, segment_ids: set[str] | None, section_ids: set[str] | None, term: str | None) -> set[str] | None:
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
