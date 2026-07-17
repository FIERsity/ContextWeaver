"""Evidence-backed v1 readiness audit for a complete translation project."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ebooklib import epub

from .coherence import scope_fingerprint
from .models import (
    AmbiguityRecord,
    Entity,
    ScopeReview,
    Section,
    SectionSummary,
    Segment,
    SourceDocument,
    TranslationRecord,
    TranslationReview,
    TranslationUnit,
)
from .pipeline import STATE, active_translations, validate_project
from .storage import read_json, read_jsonl, write_json
from .summaries import active_section_summaries


def audit_project(root: Path, *, allow_mock: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    project_path = root / "project.json"
    source_path = root / STATE / "source_document.json"
    _check(
        checks,
        "project",
        project_path.exists() and source_path.exists(),
        {
            "project_json": str(project_path),
            "source_document": str(source_path),
        },
    )
    if not project_path.exists() or not source_path.exists():
        return _finish(root, checks)
    project = read_json(project_path)
    source = SourceDocument(**read_json(source_path))
    original = root / source.original_path if source.original_path else None
    normalized = root / source.source_path
    _check(
        checks,
        "source_retention",
        bool(normalized.exists() and original is not None and original.exists()),
        {
            "normalized": str(normalized),
            "original": str(original or ""),
            "format": source.source_format,
        },
    )
    report_required = source.source_format in {"epub", "docx"}
    import_report = root / STATE / "import_report.json"
    _check(
        checks,
        "import_loss_report",
        import_report.exists() or not report_required,
        {"required_for_format": report_required, "path": str(import_report)},
    )
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    units = read_jsonl(root / STATE / "units.jsonl", TranslationUnit)
    section_ids = {item.id for item in sections}
    segment_ids = {item.id for item in segments}
    unit_segment_ids = [segment_id for unit in units for segment_id in unit.segment_ids]
    structure_ok = (
        bool(sections)
        and bool(segments)
        and bool(units)
        and len(section_ids) == len(sections)
        and len(segment_ids) == len(segments)
        and set(unit_segment_ids) == segment_ids
        and len(unit_segment_ids) == len(segment_ids)
        and all(item.section_id in section_ids for item in segments)
    )
    _check(
        checks,
        "stable_structure",
        structure_ok,
        {
            "sections": len(sections),
            "segments": len(segments),
            "units": len(units),
        },
    )
    strategy_path = root / STATE / "translation_brief.json"
    strategy = read_json(strategy_path) if strategy_path.exists() else {}
    strategy_rules = strategy.get("concept_rules", [])
    strategy_evidence_ok = all(
        bool(item.get("evidence_segment_ids")) and set(item["evidence_segment_ids"]) <= segment_ids
        for item in strategy_rules
    )
    _check(
        checks,
        "translation_strategy",
        bool(
            strategy.get("principles")
            and strategy.get("target_style")
            and strategy.get("generated_by")
            and strategy_evidence_ok
        ),
        {
            "path": str(strategy_path),
            "concept_rules": len(strategy_rules),
            "concept_evidence_valid": strategy_evidence_ok,
        },
    )
    summary_records = read_jsonl(root / STATE / "section_summaries.jsonl", SectionSummary)
    summaries = active_section_summaries(summary_records)
    nonempty_sections = {item.section_id for item in segments}
    _check(
        checks,
        "section_summaries",
        nonempty_sections <= set(summaries),
        {
            "required": len(nonempty_sections),
            "current": len(nonempty_sections & set(summaries)),
            "records": len(summary_records),
        },
    )
    ambiguities = read_jsonl(root / STATE / "ambiguities.jsonl", AmbiguityRecord)
    ambiguity_evidence_ok = all(
        item.section_id in section_ids
        and bool(item.evidence_segment_ids)
        and set(item.evidence_segment_ids) <= segment_ids
        for item in ambiguities
    )
    _check(
        checks,
        "ambiguity_evidence",
        ambiguity_evidence_ok,
        {
            "records": len(ambiguities),
            "open": sum(item.status == "open" for item in ambiguities),
        },
    )
    entities = read_jsonl(root / STATE / "entities.jsonl", Entity)
    glossary_rows = _glossary_rows(root / STATE / "glossary.csv")
    entity_evidence_ok = all(
        bool(item.evidence_segment_ids) and set(item.evidence_segment_ids) <= segment_ids
        for item in entities
    )
    glossary_evidence_ok = all(
        bool(item["evidence_segment_ids"])
        and set(item["evidence_segment_ids"]) <= segment_ids
        and (item["status"] != "approved" or bool(item["preferred_translation"]))
        for item in glossary_rows
    )
    _check(
        checks,
        "knowledge_evidence",
        entity_evidence_ok and glossary_evidence_ok,
        {
            "entities": len(entities),
            "glossary_entries": len(glossary_rows),
            "entity_evidence_valid": entity_evidence_ok,
            "glossary_evidence_valid": glossary_evidence_ok,
        },
    )
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(records)
    translated_ids = set(active) & segment_ids
    coverage = len(translated_ids) / len(segments) if segments else 0.0
    _check(
        checks,
        "translation_coverage",
        translated_ids == segment_ids,
        {
            "translated": len(translated_ids),
            "required": len(segments),
            "coverage": round(coverage, 6),
        },
    )
    non_mock = bool(active) and all(
        item.adapter != "mock" and not item.translated_text.startswith("[MOCK] ")
        for item in active.values()
    )
    _check(
        checks,
        "non_mock_translation",
        non_mock or allow_mock,
        {
            "allow_mock": allow_mock,
            "mock_active": sum(
                item.adapter == "mock" or item.translated_text.startswith("[MOCK] ")
                for item in active.values()
            ),
        },
    )
    _check(
        checks,
        "revision_integrity",
        _revision_integrity(records, segment_ids),
        {
            "records": len(records),
            "active": len(active),
        },
    )
    reviews = read_jsonl(root / STATE / "reviews.jsonl", TranslationReview)
    scope_reviews = read_jsonl(root / STATE / "scope_reviews.jsonl", ScopeReview)
    reviewed_ids = {
        record_id
        for item in reviews
        for record_id in (item.input_translation_id, item.output_translation_id)
    }
    reviewed_ids.update(
        record_id for item in scope_reviews for record_id in item.revised_translation_ids
    )
    active_reviewed = {
        segment_id for segment_id, record in active.items() if record.id in reviewed_ids
    }
    _check(
        checks,
        "segment_review_coverage",
        active_reviewed == segment_ids,
        {
            "reviewed_active": len(active_reviewed),
            "required": len(segments),
            "review_records": len(reviews),
        },
    )
    section_current = 0
    for section in sections:
        scoped = [item for item in segments if item.section_id == section.id]
        if not scoped:
            continue
        fingerprint = scope_fingerprint(root, scoped)
        if fingerprint and any(
            item.scope_type == "section"
            and item.scope_id == section.id
            and fingerprint in {item.input_digest, item.output_digest}
            for item in scope_reviews
        ):
            section_current += 1
    _check(
        checks,
        "section_review_coverage",
        section_current == len(nonempty_sections),
        {
            "current": section_current,
            "required": len(nonempty_sections),
        },
    )
    book_fingerprint = scope_fingerprint(root, segments) if segments else None
    book_current = bool(
        book_fingerprint
        and any(
            item.scope_type == "book"
            and book_fingerprint in {item.input_digest, item.output_digest}
            for item in scope_reviews
        )
    )
    _check(
        checks,
        "book_review",
        book_current,
        {
            "fingerprint_available": book_fingerprint is not None,
        },
    )
    blocking_errors: int | None = None
    if translated_ids == segment_ids and segments:
        blocking_errors = sum(item.severity == "error" for item in validate_project(root))
    _check(
        checks,
        "deterministic_validation",
        blocking_errors == 0,
        {
            "blocking_errors": blocking_errors,
            "not_run_reason": "incomplete translation" if blocking_errors is None else "",
        },
    )
    output_root = root / "output"
    artifacts = {
        name: output_root / name
        for name in ("translated.md", "bilingual.md", "translated.epub", "bilingual.epub")
    }
    artifact_exists = all(path.exists() and path.stat().st_size > 0 for path in artifacts.values())
    _check(
        checks,
        "complete_exports",
        artifact_exists,
        {name: {"path": str(path), "exists": path.exists()} for name, path in artifacts.items()},
    )
    epub_readback = artifact_exists and all(
        _epub_readable(artifacts[name]) for name in ("translated.epub", "bilingual.epub")
    )
    _check(
        checks,
        "epub_readback",
        epub_readback,
        {
            "files": [str(artifacts["translated.epub"]), str(artifacts["bilingual.epub"])],
        },
    )
    provenance_path = root / STATE / "export_metadata.json"
    provenance = read_json(provenance_path) if provenance_path.exists() else {}
    _check(
        checks,
        "provenance",
        bool(
            provenance.get("source_title")
            and provenance.get("translator")
            and provenance.get("fidelity_note")
        ),
        {"path": str(provenance_path), "translator": provenance.get("translator", "")},
    )
    report = _finish(root, checks, project_id=str(project.get("id", "")))
    return report


def _revision_integrity(records: list[TranslationRecord], segment_ids: set[str]) -> bool:
    by_id = {item.id: item for item in records}
    if len(by_id) != len(records):
        return False
    for item in records:
        if item.segment_id not in segment_ids:
            return False
        if item.revision == 1:
            if item.supersedes is not None:
                return False
            continue
        previous = by_id.get(item.supersedes or "")
        if (
            previous is None
            or previous.segment_id != item.segment_id
            or previous.revision != item.revision - 1
        ):
            return False
    return True


def _glossary_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {
                **row,
                "evidence_segment_ids": [
                    item for item in row.get("evidence_segment_ids", "").split("|") if item
                ],
            }
            for row in csv.DictReader(handle)
            if row.get("term")
        ]


def _epub_readable(path: Path) -> bool:
    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        return bool(book.spine and book.get_metadata("DC", "title"))
    except Exception:
        return False


def _check(
    checks: list[dict[str, Any]], check_id: str, passed: bool, evidence: dict[str, Any]
) -> None:
    checks.append(
        {
            "id": check_id,
            "status": "pass" if passed else "fail",
            "required": True,
            "evidence": evidence,
        }
    )


def _finish(root: Path, checks: list[dict[str, Any]], project_id: str = "") -> dict[str, Any]:
    report = {
        "schema_version": 1,
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": all(item["status"] == "pass" for item in checks if item["required"]),
        "passed": sum(item["status"] == "pass" for item in checks),
        "failed": sum(item["status"] == "fail" for item in checks),
        "checks": checks,
    }
    write_json(root / STATE / "v1_audit.json", report)
    lines = [
        "# ContextWeaver v1 readiness audit",
        "",
        f"- Ready: {'yes' if report['ready'] else 'no'}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        "",
    ]
    for item in checks:
        mark = "PASS" if item["status"] == "pass" else "FAIL"
        lines.extend(
            [
                f"## [{mark}] {item['id']}",
                "",
                "```json",
                __import__("json").dumps(item["evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    path = root / "notes" / "v1_audit.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return report
