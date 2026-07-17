import json
from dataclasses import replace
from pathlib import Path

from contextweaver.adapters import HeuristicReviewAdapter, MockTranslationAdapter
from contextweaver.audit import audit_project
from contextweaver.coherence import review_book, review_sections
from contextweaver.coherence_adapters import HeuristicCoherenceReviewAdapter
from contextweaver.models import Entity, SectionTitleRecord, TranslationRecord
from contextweaver.pipeline import (
    export_selected,
    import_document,
    init_project,
    segment_document,
    translate_project,
    translate_section_titles,
)
from contextweaver.review import review_project
from contextweaver.strategy import HeuristicBookAnalysisAdapter, analyze_project
from contextweaver.summaries import summarize_project
from contextweaver.summary_adapters import HeuristicSummaryAdapter
from contextweaver.storage import read_jsonl, write_jsonl


def _complete_project(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "book.md"
    source.write_text("# One\n\nPower shapes progress.\n\nA second paragraph.\n", encoding="utf-8")
    root = tmp_path / "project"
    init_project(root, "Audit", "en", "zh-CN")
    import_document(root, source)
    _, segments, _ = segment_document(root, unit_size=1)
    analyze_project(root, HeuristicBookAnalysisAdapter())
    summarize_project(root, HeuristicSummaryAdapter())
    translate_project(root, MockTranslationAdapter())
    translate_section_titles(root, MockTranslationAdapter())
    review_project(root, HeuristicReviewAdapter())
    reviewer = HeuristicCoherenceReviewAdapter()
    review_sections(root, reviewer)
    review_book(root, reviewer)
    export_selected(root, {"markdown", "epub"}, {"translated", "bilingual"})
    return root, segments[0].id


def test_v1_audit_proves_complete_workflow_but_rejects_mock_release(tmp_path: Path) -> None:
    root, _ = _complete_project(tmp_path)
    workflow = audit_project(root, allow_mock=True)
    assert workflow["ready"] is True
    release = audit_project(root)
    assert release["ready"] is False
    failed = {item["id"] for item in release["checks"] if item["status"] == "fail"}
    assert failed == {"non_mock_translation"}
    assert (root / "state" / "v1_audit.json").exists()
    assert (root / "notes" / "v1_audit.md").exists()


def test_audit_detects_stale_reviews_after_retranslation(tmp_path: Path) -> None:
    root, segment_id = _complete_project(tmp_path)
    translate_project(
        root, MockTranslationAdapter(), segment_ids={segment_id}, reason="new-revision"
    )
    report = audit_project(root, allow_mock=True)
    failed = {item["id"] for item in report["checks"] if item["status"] == "fail"}
    assert {"segment_review_coverage", "section_review_coverage", "book_review"} <= failed


def test_audit_rejects_knowledge_without_valid_source_evidence(tmp_path: Path) -> None:
    root, _ = _complete_project(tmp_path)
    write_jsonl(
        root / "state" / "entities.jsonl",
        [Entity("ent_bad", "Unknown", "person", evidence_segment_ids=["seg_missing"])],
    )
    report = audit_project(root, allow_mock=True)
    failed = {item["id"] for item in report["checks"] if item["status"] == "fail"}
    assert "knowledge_evidence" in failed


def test_audit_rejects_concept_rule_without_valid_source_evidence(tmp_path: Path) -> None:
    root, _ = _complete_project(tmp_path)
    brief_path = root / "state" / "translation_brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief["concept_rules"] = [
        {
            "source_term": "power",
            "preferred_rendering": "权力",
            "guidance": "Use the institutional sense.",
            "evidence_segment_ids": ["seg_missing"],
            "confidence": 0.9,
        }
    ]
    brief_path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    report = audit_project(root, allow_mock=True)
    failed = {item["id"] for item in report["checks"] if item["status"] == "fail"}
    assert "translation_strategy" in failed


def test_audit_rejects_section_title_bound_to_wrong_source_digest(tmp_path: Path) -> None:
    root, _ = _complete_project(tmp_path)
    path = root / "state" / "section_titles.jsonl"
    records = read_jsonl(path, SectionTitleRecord)
    write_jsonl(path, [replace(records[0], source_sha256="wrong")])
    report = audit_project(root, allow_mock=True)
    failed = {item["id"] for item in report["checks"] if item["status"] == "fail"}
    assert "section_title_revision_integrity" in failed


def test_release_audit_uses_strict_numeric_validation(tmp_path: Path) -> None:
    root, segment_id = _complete_project(tmp_path)
    path = root / "state" / "translations.jsonl"
    records = read_jsonl(path, TranslationRecord)
    write_jsonl(
        path,
        [
            replace(item, translated_text=f"{item.translated_text} 2025")
            if item.segment_id == segment_id
            else item
            for item in records
        ],
    )
    report = audit_project(root, allow_mock=True)
    checks = {item["id"]: item for item in report["checks"]}
    assert checks["deterministic_validation"]["status"] == "fail"
    assert checks["deterministic_validation"]["evidence"]["blocking_errors"] == 1
