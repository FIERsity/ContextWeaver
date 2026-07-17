"""Deterministic structural and consistency validation rules."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import re
from collections.abc import Callable

from .markdown import format_signature
from .models import GlossaryEntry, ReviewIssue, Segment, TranslationRecord
from .pipeline import active_translations, stable_id


def quality_issues(
    segments: list[Segment],
    records: list[TranslationRecord],
    glossary: list[GlossaryEntry],
    numeric_mode: str = "relaxed",
) -> list[ReviewIssue]:
    if numeric_mode not in {"relaxed", "balanced", "strict"}:
        raise ValueError("numeric_mode must be 'relaxed', 'balanced', or 'strict'")
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
        # Both modes compare semantic quantities rather than surface notation.
        # Strictness controls mismatch severity, not whether 2,000 and a
        # source-backed written/scaled rendering describe the same quantity.
        compared_source = _balanced_numeric_anchors(source_numbers)
        compared_target = _balanced_numeric_anchors(target_numbers)
        if compared_source != compared_target:
            missing = Counter(compared_source) - Counter(compared_target)
            extra = Counter(compared_target) - Counter(compared_source)
            # Production translation is source-preserving by default: a source
            # quantity that disappears or changes still blocks the run, while
            # target-only anchors are deferred to the strict publication audit.
            # This avoids treating source-backed naturalizations such as
            # ``May`` -> ``5月`` as invented data when a parser cannot prove the
            # equivalence yet.
            if numeric_mode == "relaxed":
                # Repeating a shared year or quantity once instead of twice is
                # normal Chinese compression, so working validation compares
                # semantic presence rather than multiplicity.
                source_set = set(compared_source)
                target_set = set(compared_target)
                # Chinese commonly establishes the century once and then says
                # simply ``60年代``. Accept the abbreviated decade only when
                # the full source decade supplies its century evidence.
                for source_anchor in source_numbers:
                    if source_anchor.startswith("decade:"):
                        decade = int(source_anchor.removeprefix("decade:"))
                        suffix = str(decade % 100)
                        if source_anchor not in target_set and suffix in target_set:
                            target_set.add(source_anchor)
                missing = Counter(source_set - target_set)
                extra = Counter(target_set - source_set)
                if not missing:
                    continue
            severity = "error" if missing or numeric_mode == "strict" else "warning"
            issues.append(
                _issue(
                    "numeric_anchor_mismatch",
                    (
                        f"Source numeric anchors {source_numbers} differ from translation "
                        f"{target_numbers}; missing {sorted(missing.elements())}, "
                        f"extra {sorted(extra.elements())}"
                    ),
                    segment.id,
                    severity,
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


def _balanced_numeric_anchors(anchors: list[str]) -> list[str]:
    """Align surface quantity/ordinal forms while retaining typed dates and periods."""
    return sorted(
        item.removeprefix("quantity:").removeprefix("ordinal:") for item in anchors
    )


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

    def replace_many(
        pattern: str, convert: Callable[[re.Match[str]], list[object]], value: str
    ) -> None:
        nonlocal working

        def substitution(match: re.Match[str]) -> str:
            anchors.extend(f"{value}:{item}" for item in convert(match))
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
    replace(r"(?<!\d)(\d{4})\s*年代", lambda match: int(match.group(1)), "decade")
    shared_decades = re.compile(
        r"(?<!\d)(\d{1,2})\s*世纪\s*((?:\d{1,2}\s*(?:年代)?\s*(?:和|与|至|到|、)\s*)+\d{1,2}\s*年代)"
    )
    match = shared_decades.search(working)
    while match:
        century = int(match.group(1))
        anchors.extend(
            f"decade:{(century - 1) * 100 + int(value)}"
            for value in re.findall(r"\d{1,2}", match.group(2))
        )
        working = working[: match.start()] + " " + working[match.end() :]
        match = shared_decades.search(working)
    replace(
        r"(?<!\d)(\d{1,2})\s*世纪\s*(\d{1,2})\s*年代",
        lambda match: (int(match.group(1)) - 1) * 100 + int(match.group(2)),
        "decade",
    )
    english_centuries = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
        "ninth": 9,
        "tenth": 10,
        "eleventh": 11,
        "twelfth": 12,
        "thirteenth": 13,
        "fourteenth": 14,
        "fifteenth": 15,
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
        r"\b(\d+)(?:st|nd|rd|th)[\s-]+century\b",
        lambda match: int(match.group(1)),
        "century",
    )
    replace(
        r"(?<!\d)(\d{1,2})\s*世纪",
        lambda match: int(match.group(1)),
        "century",
    )
    replace(r"(?:第\s*一个|最初\s*一个)世纪", lambda _match: 1, "century")
    replace(r"\bWorld\s+War\s+II\b", lambda _match: 2, "world-war")
    replace(r"第\s*(?:二|2)\s*次世界大战", lambda _match: 2, "world-war")
    replace(r"\b(?:a|one)\s+millennium\b", lambda _match: 1_000, "quantity")
    replace(
        r"\ba\s+thousand\b",
        lambda _match: 1_000,
        "quantity",
    )
    replace(r"上千", lambda _match: 1_000, "quantity")
    replace(r"\b(\d+)(?:st|nd|rd|th)\b", lambda match: int(match.group(1)), "ordinal")
    replace(
        r"第\s*(\d+)(?!\s*(?:章|次世界大战))",
        lambda match: int(match.group(1)),
        "ordinal",
    )
    magnitudes = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
    word_numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    number_words = "|".join(word_numbers)
    magnitude_words = "hundred|thousand|million|billion"
    replace(
        rf"\bnineteen[\s-]+((?:{number_words})(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine))?)\b",
        lambda match: 1900 + _english_number_value(match.group(1), word_numbers, magnitudes),
        "quantity",
    )
    replace_many(
        rf"\bbetween(?:\s+the\s+ages?\s+of)?\s+({number_words})\s+and\s+({number_words})\b",
        lambda match: [
            word_numbers[match.group(1).casefold()],
            word_numbers[match.group(2).casefold()],
        ],
        "quantity",
    )
    compound_number = (
        rf"\b(?:{number_words})(?:[\s-]+(?:{number_words}|{magnitude_words}|and))+\b"
    )
    replace(
        compound_number,
        lambda match: _english_number_value(match.group(0), word_numbers, magnitudes),
        "quantity",
    )
    replace(
        rf"\b({number_words})\s+hundred\s+thousand\b",
        lambda match: word_numbers[match.group(1).casefold()] * 100_000,
        "quantity",
    )
    replace(
        rf"\b({number_words})\s+(hundred|thousand|million|billion)\b",
        lambda match: word_numbers[match.group(1).casefold()]
        * magnitudes[match.group(2).casefold()],
        "quantity",
    )
    replace(r"\ba\s+million\b", lambda _match: 1_000_000, "quantity")
    chinese_number = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "两": 2,
    }
    replace(
        r"([一二三四五六七八九两])万([一二三四五六七八九两])千",
        lambda match: chinese_number[match.group(1)] * 10_000
        + chinese_number[match.group(2)] * 1_000,
        "quantity",
    )
    replace(
        r"([一二三四五六七八九两])千([一二三四五六七八九两])百",
        lambda match: chinese_number[match.group(1)] * 1_000
        + chinese_number[match.group(2)] * 100,
        "quantity",
    )
    replace(
        r"([一二三四五六七八九])十万",
        lambda match: chinese_number[match.group(1)] * 100_000,
        "quantity",
    )
    replace(
        r"([一二三四五六七八九两])\s*(千|百万|十亿)",
        lambda match: chinese_number[match.group(1)]
        * {"千": 1_000, "百万": 1_000_000, "十亿": 1_000_000_000}[match.group(2)],
        "quantity",
    )
    replace(
        r"([一二三四五六七八九两])百",
        lambda match: chinese_number[match.group(1)] * 100,
        "quantity",
    )
    replace(
        r"([一二三四五六七八九两])万",
        lambda match: chinese_number[match.group(1)] * 10_000,
        "quantity",
    )
    replace(
        r"(?<![第数一二三四五六七八九十百千万亿])([一二三四五六七八九两]?)十([一二三四五六七八九]?)(?![百千万亿])",
        lambda match: (chinese_number[match.group(1)] if match.group(1) else 1) * 10
        + (chinese_number[match.group(2)] if match.group(2) else 0),
        "quantity",
    )
    replace_many(
        r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)\s*[‒–—-]\s*(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion)\b",
        lambda match: [
            _scaled_number(match.group(1), magnitudes[match.group(3).casefold()]),
            _scaled_number(match.group(2), magnitudes[match.group(3).casefold()]),
        ],
        "quantity",
    )
    replace(
        r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion)\b",
        lambda match: _scaled_number(match.group(1), magnitudes[match.group(2).casefold()]),
        "quantity",
    )
    replace(
        r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)\s*多?\s*(万|亿)",
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
    full_months = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    for month, name in enumerate(full_months, 1):
        anchor = f"month:{month}"
        contextual_month = rf"\b(?:in|on|by|during|until|from|since|through|late|early)\s+{name}\b"
        dated_month = rf"\b{name}\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
        if anchor not in anchors and re.search(
            rf"(?:{contextual_month}|{dated_month})", working, flags=re.IGNORECASE
        ):
            anchors.append(anchor)
    return sorted(anchors)


def _chapter_number(value: str, words: dict[str, int]) -> int:
    return int(value) if value.isdigit() else words[value]


def _scaled_number(number: str, multiplier: int) -> str:
    value = Decimal(number.replace(",", "")) * multiplier
    return format(value.normalize(), "f")


def _english_number_value(
    phrase: str, words: dict[str, int], magnitudes: dict[str, int]
) -> int:
    """Parse a compound English cardinal such as `seven hundred and fifty`."""
    total = current = 0
    for token in re.findall(r"[a-z]+", phrase.casefold()):
        if token == "and":
            continue
        if token in words:
            current += words[token]
        elif token == "hundred":
            current = max(current, 1) * 100
        elif token in magnitudes:
            total += max(current, 1) * magnitudes[token]
            current = 0
    return total + current


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
    for slogan in re.findall(r"\b[A-Z]{2,}(?:[\s.,!?;:'’\-]+[A-Z]{2,})+\b", text):
        candidates.difference_update(re.findall(r"[A-Z]{2,8}", slogan))
    if re.search(r"\bWorld\s+War\s+II\b", text, flags=re.IGNORECASE):
        candidates.discard("II")
    return sorted(
        candidate
        for candidate in candidates - common_words
        if not re.fullmatch(r"[IVXLCDM]+", candidate)
    )


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
