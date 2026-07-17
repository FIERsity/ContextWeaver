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
        expected = (
            format_signature(segment.raw) if segment.raw else sorted(segment.format_signature)
        )
        actual = format_signature(output)
        if expected != actual:
            issues.append(
                _issue(
                    "format_mismatch",
                    f"Expected format markers {expected}, found {actual}",
                    segment.id,
                    "error",
                )
            )
        if record.adapter == "structural-passthrough":
            continue
        if len(output.strip()) < max(1, len(segment.text.strip()) // 20):
            issues.append(
                _issue(
                    "suspiciously_short",
                    "Translation is unusually short relative to source",
                    segment.id,
                    "warning",
                )
            )
        source_numbers = _numeric_anchors(segment.text)
        target_numbers = _numeric_anchors(output)
        if source_numbers != target_numbers:
            issues.append(
                _issue(
                    "numeric_anchor_mismatch",
                    f"Source numeric anchors {source_numbers} differ from translation {target_numbers}",
                    segment.id,
                    "error",
                )
            )
        for acronym in _acronyms(segment.text):
            approved_renderings = [
                rendering
                for entry in glossary
                if entry.status == "approved" and entry.term.casefold() == acronym.casefold()
                for rendering in [entry.preferred_translation, *entry.allowed_variants]
                if rendering
            ]
            if acronym not in output and not any(
                rendering.casefold() in output.casefold() for rendering in approved_renderings
            ):
                issues.append(
                    _issue(
                        "acronym_missing",
                        f"Source acronym '{acronym}' is absent from translation",
                        segment.id,
                        "warning",
                    )
                )
        repeated[segment.text.casefold()].add(output.casefold())
        for entry in glossary:
            if entry.status != "approved" or not entry.preferred_translation:
                continue
            if _contains_term(segment.text, entry.term):
                variants = [entry.preferred_translation, *entry.allowed_variants]
                if not any(item.casefold() in output.casefold() for item in variants):
                    issues.append(
                        _issue(
                            "terminology_mismatch",
                            f"Expected approved translation for term '{entry.term}'",
                            segment.id,
                            "warning",
                        )
                    )
    inconsistent = {text for text, outputs in repeated.items() if len(outputs) > 1}
    for segment in segments:
        if segment.text.casefold() in inconsistent:
            issues.append(
                _issue(
                    "repeated_source_inconsistent",
                    "Identical source text has inconsistent translations",
                    segment.id,
                    "warning",
                )
            )
    return issues


def _issue(kind: str, message: str, segment_id: str, severity: str) -> ReviewIssue:
    return ReviewIssue(
        stable_id("issue", kind, segment_id, message), kind, message, segment_id, severity
    )  # type: ignore[arg-type]


def _numbers(text: str) -> list[str]:
    values = re.findall(
        r"(?<![A-Za-z0-9_])(?:[$€£¥]\s*)?\d+(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9_])",
        text,
    )
    return sorted(re.sub(r"[^\d.]", "", value) for value in values)


_MONTH_PATTERNS = (
    (r"jan(?:uary)?", 1),
    (r"feb(?:ruary)?", 2),
    (r"mar(?:ch)?", 3),
    (r"apr(?:il)?", 4),
    (r"may", 5),
    (r"jun(?:e)?", 6),
    (r"jul(?:y)?", 7),
    (r"aug(?:ust)?", 8),
    (r"sep(?:t(?:ember)?)?", 9),
    (r"oct(?:ober)?", 10),
    (r"nov(?:ember)?", 11),
    (r"dec(?:ember)?", 12),
)
_ZH_MONTHS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}


def _numeric_anchors(text: str) -> list[str]:
    """Canonicalize explicit numbers plus semantically numeric calendar months."""
    anchors = _numbers(text)
    numeric_months = [
        int(match.group(1)) for match in re.finditer(r"(?<!\d)(1[0-2]|0?[1-9])\s*月", text)
    ]
    for month in numeric_months:
        value = str(month)
        if value in anchors:
            anchors.remove(value)
        anchors.append(f"month:{month}")
    for word, month in _ZH_MONTHS.items():
        if re.search(rf"(?<![一二三四五六七八九十]){word}月", text):
            anchors.append(f"month:{month}")
    lowered = text.casefold()
    for pattern, month in _MONTH_PATTERNS:
        date_pattern = (
            rf"(?:\b{pattern}\b\.?\s+(?:of\s+)?\d{{4}}"
            rf"|\d{{4}}\s+\b{pattern}\b\.?)"
        )
        if re.search(date_pattern, lowered):
            anchors.append(f"month:{month}")
    return sorted(anchors)


def _acronyms(text: str) -> list[str]:
    common_words = {
        "A",
        "ALL",
        "AND",
        "ARE",
        "AS",
        "AT",
        "BE",
        "BEEN",
        "BUT",
        "BY",
        "FOR",
        "FROM",
        "HAVE",
        "HERE",
        "IN",
        "IS",
        "IT",
        "NOT",
        "OF",
        "ON",
        "OR",
        "THAT",
        "THE",
        "THIS",
        "TO",
        "WAS",
        "WE",
        "WERE",
        "WITH",
    }
    candidates = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,8}(?![A-Za-z])", text))
    return sorted(candidates - common_words)


def _contains_term(text: str, term: str) -> bool:
    """Match word-like Latin terms without treating them as substrings of words."""
    if re.fullmatch(r"[A-Za-z0-9_]+", term):
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                text,
                flags=re.IGNORECASE,
            )
        )
    return term.casefold() in text.casefold()
