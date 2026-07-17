"""Deterministic structural and consistency validation rules."""

from __future__ import annotations

from collections import defaultdict
import re

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
        # Recompute from retained source markup so parser bug fixes also apply
        # to existing, resumable projects without forcing Segment ID changes.
        expected = format_signature(segment.raw) if segment.raw else sorted(segment.format_signature)
        actual = format_signature(output)
        if expected != actual:
            issues.append(_issue("format_mismatch", f"Expected format markers {expected}, found {actual}", segment.id, "error"))
        if len(output.strip()) < max(1, len(segment.text.strip()) // 20):
            issues.append(_issue("suspiciously_short", "Translation is unusually short relative to source", segment.id, "warning"))
        source_numbers = _numbers(segment.text)
        target_numbers = _numbers(output)
        if source_numbers != target_numbers:
            issues.append(_issue(
                "numeric_anchor_mismatch",
                f"Source numeric anchors {source_numbers} differ from translation {target_numbers}",
                segment.id, "error",
            ))
        for acronym in _acronyms(segment.text):
            if acronym not in output:
                issues.append(_issue(
                    "acronym_missing", f"Source acronym '{acronym}' is absent from translation",
                    segment.id, "warning",
                ))
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


def _numbers(text: str) -> list[str]:
    values = re.findall(
        r"(?<![A-Za-z0-9_])(?:[$€£¥]\s*)?\d+(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9_])",
        text,
    )
    return sorted(re.sub(r"[^\d.]", "", value) for value in values)


def _acronyms(text: str) -> list[str]:
    common_words = {
        "A", "ALL", "AND", "ARE", "AS", "AT", "BE", "BEEN", "BUT", "BY",
        "FOR", "FROM", "HAVE", "HERE", "IN", "IS", "IT", "NOT", "OF", "ON",
        "OR", "THAT", "THE", "THIS", "TO", "WAS", "WE", "WERE", "WITH",
    }
    candidates = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,8}(?![A-Za-z])", text))
    return sorted(candidates - common_words)
