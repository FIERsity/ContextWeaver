"""Deterministic structural and consistency validation rules."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re
from collections.abc import Callable

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
    working = text
    anchors: list[str] = []

    def replace(pattern: str, convert: Callable[[re.Match[str]], object], value: str) -> None:
        nonlocal working

        def substitution(match: re.Match[str]) -> str:
            anchors.append(f"{value}:{convert(match)}")
            return " "

        working = re.sub(pattern, substitution, working, flags=re.IGNORECASE)

    chapter_numbers = {
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
    chapter_word = "|".join(sorted(chapter_numbers, key=len, reverse=True))
    chapter_range = re.compile(r"\bchapters?\s+(\d+)\s+(?:through|to|and)\s+(\d+)\b", re.IGNORECASE)
    match = chapter_range.search(working)
    while match:
        anchors.extend([f"chapter:{int(match.group(1))}", f"chapter:{int(match.group(2))}"])
        working = working[: match.start()] + " " + working[match.end() :]
        match = chapter_range.search(working)
    chinese_chapter_range = re.compile(
        rf"第\s*({chapter_word}|\d+)\s*章\s*(?:至|到|和|与|—|–|-)\s*第?\s*({chapter_word}|\d+)\s*章"
    )
    match = chinese_chapter_range.search(working)
    while match:
        anchors.extend(
            [
                f"chapter:{_chapter_number(match.group(1), chapter_numbers)}",
                f"chapter:{_chapter_number(match.group(2), chapter_numbers)}",
            ]
        )
        working = working[: match.start()] + " " + working[match.end() :]
        match = chinese_chapter_range.search(working)
    replace(r"\bchapters?\s+(\d+)\b", lambda match: int(match.group(1)), "chapter")
    replace(
        rf"第\s*({chapter_word}|\d+)\s*章",
        lambda match: _chapter_number(match.group(1), chapter_numbers),
        "chapter",
    )
    replace(r"\b(\d{2}00)s\b", lambda match: int(match.group(1)) // 100 + 1, "century")
    replace(r"\b(\d{4})s\b", lambda match: int(match.group(1)), "decade")
    shared_decades = re.compile(
        r"(?<!\d)(\d{1,2})\s*世纪\s*(\d{1,2})\s*年代\s*(?:和|与|至|到|、)\s*(\d{1,2})\s*年代"
    )
    match = shared_decades.search(working)
    while match:
        century = int(match.group(1))
        anchors.extend(
            [
                f"decade:{(century - 1) * 100 + int(match.group(2))}",
                f"decade:{(century - 1) * 100 + int(match.group(3))}",
            ]
        )
        working = working[: match.start()] + " " + working[match.end() :]
        match = shared_decades.search(working)
    replace(
        r"(?<!\d)(\d{1,2})\s*世纪\s*(\d{1,2})\s*年代",
        lambda match: (int(match.group(1)) - 1) * 100 + int(match.group(2)),
        "decade",
    )
    english_centuries = {
        "sixteenth": 16,
        "seventeenth": 17,
        "eighteenth": 18,
        "nineteenth": 19,
        "twentieth": 20,
        "twenty-first": 21,
    }
    century_words = "|".join(english_centuries)
    coordinated_centuries = re.compile(
        rf"\b({century_words})\s+and\s+({century_words})\s+centuries\b", re.IGNORECASE
    )
    match = coordinated_centuries.search(working)
    while match:
        anchors.extend(
            [
                f"century:{english_centuries[match.group(1).casefold()]}",
                f"century:{english_centuries[match.group(2).casefold()]}",
            ]
        )
        working = working[: match.start()] + " " + working[match.end() :]
        match = coordinated_centuries.search(working)
    replace(
        rf"\b({century_words})[\s-]+century\b",
        lambda match: english_centuries[match.group(1).casefold()],
        "century",
    )
    replace(
        r"(?<!\d)(\d{1,2})\s*世纪",
        lambda match: int(match.group(1)),
        "century",
    )
    replace(r"\bWorld\s+War\s+II\b", lambda _match: 2, "world-war")
    replace(r"第\s*(?:二|2)\s*次世界大战", lambda _match: 2, "world-war")
    magnitudes = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
    replace(
        r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*(thousand|million|billion)\b",
        lambda match: _scaled_number(match.group(1), magnitudes[match.group(2).casefold()]),
        "quantity",
    )
    replace(
        r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*(万|亿)",
        lambda match: _scaled_number(
            match.group(1), 10_000 if match.group(2) == "万" else 100_000_000
        ),
        "quantity",
    )
    anchors.extend(_numbers(working))
    numeric_months = [
        int(match.group(1)) for match in re.finditer(r"(?<!\d)(1[0-2]|0?[1-9])\s*月", working)
    ]
    for month in numeric_months:
        value = str(month)
        if value in anchors:
            anchors.remove(value)
        anchors.append(f"month:{month}")
    for word, month in _ZH_MONTHS.items():
        if re.search(rf"(?<![一二三四五六七八九十]){word}月", working):
            anchors.append(f"month:{month}")
    lowered = working.casefold()
    for pattern, month in _MONTH_PATTERNS:
        date_pattern = (
            rf"(?:\b{pattern}\b\.?\s+(?:of\s+)?\d{{4}}"
            rf"|\b{pattern}\b\.?\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}}"
            rf"|\d{{4}}\s+\b{pattern}\b\.?)"
        )
        if re.search(date_pattern, lowered):
            anchors.append(f"month:{month}")
    return sorted(anchors)


def _chapter_number(value: str, words: dict[str, int]) -> int:
    return int(value) if value.isdigit() else words[value]


def _scaled_number(number: str, multiplier: int) -> str:
    value = Decimal(number) * multiplier
    return format(value.normalize(), "f")


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
    if re.search(r"\bWorld\s+War\s+II\b", text, flags=re.IGNORECASE):
        candidates.discard("II")
    return sorted(candidates - common_words)


def _contains_term(text: str, term: str) -> bool:
    """Match word-like Latin terms without treating them as substrings of words."""
    if re.fullmatch(r"[A-Za-z0-9_]+", term):
        flags = 0 if len(term) > 1 and term.isupper() else re.IGNORECASE
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                text,
                flags=flags,
            )
        )
    return term.casefold() in text.casefold()
