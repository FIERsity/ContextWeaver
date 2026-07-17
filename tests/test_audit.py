from pathlib import Path

from contextweaver.adapters import HeuristicReviewAdapter, MockTranslationAdapter
from contextweaver.audit import audit_project
from contextweaver.coherence import review_book, review_sections
from contextweaver.coherence_adapters import HeuristicCoherenceReviewAdapter
from contextweaver.pipeline import (
    export_selected,
    import_document,
    init_project,
    segment_document,
    translate_project,
)
from contextweaver.review import review_project
from contextweaver.strategy import HeuristicBookAnalysisAdapter, analyze_project
from contextweaver.summaries import summarize_project
from contextweaver.summary_adapters import HeuristicSummaryAdapter


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
