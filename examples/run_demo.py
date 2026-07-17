"""Run the complete offline pipeline from a source checkout."""

from __future__ import annotations

import shutil
from pathlib import Path

from contextweaver.adapters import MockTranslationAdapter
from contextweaver.pipeline import export_project, import_document, init_project, segment_document, translate_project, validate_project

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "demo-project"

if PROJECT.exists():
    shutil.rmtree(PROJECT)

init_project(PROJECT, "The Observatory", "en", "zh-CN")
import_document(PROJECT, HERE / "sample-book.md")
sections, segments, units = segment_document(PROJECT, unit_size=2)
written, _ = translate_project(PROJECT, MockTranslationAdapter())
issues = validate_project(PROJECT)
translated, bilingual = export_project(PROJECT)
print(f"sections={len(sections)} segments={len(segments)} units={len(units)} translated={written} issues={len(issues)}")
print(f"translated={translated}")
print(f"bilingual={bilingual}")

