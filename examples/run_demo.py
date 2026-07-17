"""Run the complete offline pipeline from a source checkout."""

from __future__ import annotations

import shutil
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
    validate_project,
)
from contextweaver.review import review_project
from contextweaver.strategy import HeuristicBookAnalysisAdapter, analyze_project
from contextweaver.summaries import summarize_project
from contextweaver.summary_adapters import HeuristicSummaryAdapter

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "demo-project"

if PROJECT.exists():
    shutil.rmtree(PROJECT)

init_project(PROJECT, "The Observatory", "en", "zh-CN")
import_document(PROJECT, HERE / "sample-book.md")
sections, segments, units = segment_document(PROJECT, unit_size=2)
brief = analyze_project(PROJECT, HeuristicBookAnalysisAdapter())
summary_count, ambiguity_count, _ = summarize_project(PROJECT, HeuristicSummaryAdapter())
written, _ = translate_project(PROJECT, MockTranslationAdapter())
reviewed, revised, _ = review_project(PROJECT, HeuristicReviewAdapter())
scope_reviewer = HeuristicCoherenceReviewAdapter()
section_reviewed, section_revised, _ = review_sections(PROJECT, scope_reviewer)
book_reviewed, book_revised, _ = review_book(PROJECT, scope_reviewer)
issues = validate_project(PROJECT)
artifacts = export_selected(PROJECT, {"markdown", "epub"}, {"translated", "bilingual"})
audit = audit_project(PROJECT, allow_mock=True)
print(
    f"sections={len(sections)} segments={len(segments)} units={len(units)} translated={written} issues={len(issues)}"
)
print(f"strategy={brief['genre']} human_review_required={brief['human_review_required']}")
print(f"summaries={summary_count} ambiguities={ambiguity_count}")
print(f"reviewed={reviewed} revised={revised}")
print(
    f"coherence_scopes={section_reviewed + book_reviewed} "
    f"coherence_revisions={section_revised + book_revised}"
)
print(f"artifacts={','.join(str(path) for path in artifacts)}")
print(f"v1_audit_ready={audit['ready']} passed={audit['passed']} failed={audit['failed']}")
