"""Deterministic structural and consistency validation rules."""

from __future__ import annotations

from collections import defaultdict

from .markdown import format_signature
from .models import GlossaryEntry, ReviewIssue, Segment, TranslationRecord
from .pipeline import active_translations, stable_id


def quality_issues(
    segments: list[Segment], records: list[TranslationRecord], glossary: list[GlossaryEntry]
) -> list[ReviewIssue]:
    active = active_translations(records)
    issues: list[ReviewIssue] = []
    repeated: dict[str, set[str]] = defaultdict(set)
    for segment in segments:
        record = active.get(segment.id)
        if not record:
            continue
        output = record.translated_text.removeprefix("[MOCK] ")
        expected = sorted(segment.format_signature)
        actual = format_signature(output)
        if expected != actual:
            issues.append(_issue("format_mismatch", f"Expected format markers {expected}, found {actual}", segment.id, "error"))
        if len(output.strip()) < max(1, len(segment.text.strip()) // 20):
            issues.append(_issue("suspiciously_short", "Translation is unusually short relative to source", segment.id, "warning"))
        repeated[segment.text.casefold()].add(output.casefold())
        for entry in glossary:
            if entry.status != "approved" or not entry.preferred_translation:
                continue
            if entry.term.casefold() in segment.text.casefold():
                variants = [entry.preferred_translation, *entry.allowed_variants]
                if not any(item.casefold() in output.casefold() for item in variants):
                    issues.append(_issue("terminology_mismatch", f"Expected approved translation for term '{entry.term}'", segment.id, "warning"))
    inconsistent = {text for text, outputs in repeated.items() if len(outputs) > 1}
    for segment in segments:
        if segment.text.casefold() in inconsistent:
            issues.append(_issue("repeated_source_inconsistent", "Identical source text has inconsistent translations", segment.id, "warning"))
    return issues


def _issue(kind: str, message: str, segment_id: str, severity: str) -> ReviewIssue:
    return ReviewIssue(stable_id("issue", kind, segment_id, message), kind, message, segment_id, severity)  # type: ignore[arg-type]

