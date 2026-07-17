"""Deterministic structural and consistency validation rules."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import re
from collections.abc import Callable

from .markdown import format_signature, plain_text
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
        # These adapters intentionally retain source-visible text: image-only
        # structure and bibliographic citations are not semantically translated
        # prose. Their Markdown structure is still checked above.
        if record.adapter in {"structural-passthrough", "bibliography-passthrough"}:
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
        target_numbers = _numeric_anchors(plain_text(output))
        # Both modes compare semantic quantities rather than surface notation.
        # Strictness controls mismatch severity, not whether 2,000 and a
        # source-backed written/scaled rendering describe the same quantity.
        compared_source = _balanced_numeric_anchors(source_numbers)
        compared_target = _balanced_numeric_anchors(target_numbers)
        if compared_source != compared_target:
            # Repetition is often deliberately compressed in Chinese prose.
            # Validate that every distinct factual anchor survives, instead of
            # requiring it to appear the same number of times.
            source_set = set(compared_source)
            target_set = set(compared_target)
            # A Chinese ``60年代`` inherits its century from the source context.
            # Resolve it only when its matching source decade is unambiguous.
            for target_anchor in list(target_set):
                if re.fullmatch(r"\d{2}", target_anchor) and target_anchor not in source_set:
                    matches = [
                        item
                        for item in source_set
                        if item.startswith("decade:")
                        and str(int(item.removeprefix("decade:")) % 100) == target_anchor
                    ]
                    if len(matches) == 1:
                        target_set.add(matches[0])
                        target_set.remove(target_anchor)
            # A stated decade carries its century evidence even when Chinese
            # does not restate the century as a separate phrase.
            for target_anchor in list(target_set):
                if target_anchor.startswith("decade:"):
                    decade = int(target_anchor.removeprefix("decade:"))
                    inferred_century = f"century:{decade // 100 + 1}"
                    if inferred_century in source_set:
                        target_set.add(inferred_century)
            missing = Counter(source_set - target_set)
            extra = Counter(target_set - source_set)
            if numeric_mode == "relaxed":
                for anchor in list(missing):
                    if re.fullmatch(r"0\d+", anchor):
                        del missing[anchor]
            if not missing and not extra:
                continue
            if numeric_mode == "relaxed" and not missing:
                continue
            # A target-only number can be a legitimate explicit rendering of
            # source context (for example a month or a localized heading).
            # Working validation retains it as a warning; the release audit
            # remains conservative and requires it to be resolved.
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
        # Image placeholders share the same visible alt text while preserving
        # different destinations. They are structural passthrough content, not
        # repeated prose that should have matching translations.
        if not _is_image_only(segment):
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
        if not _is_image_only(segment) and segment.text.casefold() in inconsistent:
            issues.append(
                _issue(
                    "repeated_source_inconsistent",
                    "Identical source text has inconsistent translations",
                    segment.id,
                    "warning",
                )
            )
    return issues


def _is_image_only(segment: Segment) -> bool:
    return bool(re.fullmatch(r"\s*!\[[^]]*\]\([^)]+\)\s*", segment.raw or segment.text))


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
        r"(?<![A-Za-z0-9_])(?:[$€£¥]\s*)?(?:\d+\.\d+(?=[A-Za-z])|\d+(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9_]))",
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
    # Lexicalized names such as COVID-19 are terminology, not quantities. Their
    # localized forms (for example ``新冠``) are covered by terminology review.
    working = re.sub(r"\bCOVID-?19\b", " ", text, flags=re.IGNORECASE)
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

    # Bibliographies commonly abbreviate parliamentary column ranges, e.g.
    # ``cc604-18``.  Expand the omitted prefix so it compares with the
    # natural target form ``第604—618栏``.
    abbreviated_columns = re.compile(r"\bcc(\d+)[‒–—-](\d{1,2})\b", re.IGNORECASE)
    match = abbreviated_columns.search(working)
    while match:
        start = match.group(1)
        end = start[: len(start) - len(match.group(2))] + match.group(2)
        anchors.extend([start, end])
        working = working[: match.start()] + " " + working[match.end() :]
        match = abbreviated_columns.search(working)

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
    english_chapter_list = re.compile(
        r"\bchapters?\s+(\d+)\s*,\s*(\d+)\s*(?:,\s*and\s+|,\s*|and\s+)(\d+)\b",
        re.IGNORECASE,
    )
    match = english_chapter_list.search(working)
    while match:
        anchors.extend(f"chapter:{int(value)}" for value in match.groups())
        working = working[: match.start()] + " " + working[match.end() :]
        match = english_chapter_list.search(working)
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
    chinese_chapter_list = re.compile(r"第\s*((?:\d+|[一二三四五六七八九十]+)(?:\s*、\s*(?:\d+|[一二三四五六七八九十]+))+?)\s*章")
    match = chinese_chapter_list.search(working)
    while match:
        anchors.extend(
            f"chapter:{_chapter_number(value, chapter_numbers)}"
            for value in re.findall(r"\d+|[一二三四五六七八九十]+", match.group(1))
        )
        working = working[: match.start()] + " " + working[match.end() :]
        match = chinese_chapter_list.search(working)
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
    chinese_century_list = re.compile(r"(?<!\d)(\d{1,2})\s*、\s*(\d{1,2})\s*世纪")
    match = chinese_century_list.search(working)
    while match:
        anchors.extend(f"century:{int(value)}" for value in match.groups())
        working = working[: match.start()] + " " + working[match.end() :]
        match = chinese_century_list.search(working)
    chinese_centuries = {
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
        "十三": 13,
        "十四": 14,
        "十五": 15,
        "十六": 16,
        "十七": 17,
        "十八": 18,
        "十九": 19,
        "二十": 20,
        "二十一": 21,
    }
    chinese_century_words = "|".join(sorted(chinese_centuries, key=len, reverse=True))
    replace(
        rf"(?<![一二三四五六七八九十])({chinese_century_words})\s*世纪",
        lambda match: chinese_centuries[match.group(1)],
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
    replace(r"(?<![一二三四五六七八九两])千余?年", lambda _match: 1_000, "quantity")
    replace(
        r"\ba\s+thousand\b",
        lambda _match: 1_000,
        "quantity",
    )
    replace(r"上千", lambda _match: 1_000, "quantity")
    replace(r"数千", lambda _match: 1_000, "quantity")
    replace(r"\b(\d+)(?:st|nd|rd|th)\b", lambda match: int(match.group(1)), "ordinal")
    replace(
        r"第\s*(\d+)(?!\s*(?:章|次世界大战))",
        lambda match: int(match.group(1)),
        "ordinal",
    )
    magnitudes = {
        "hundred": 100,
        "thousand": 1_000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
        "trillion": 1_000_000_000_000,
    }
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
    magnitude_words = "hundred|thousand|million|billion|trillion"
    replace_many(
        rf"\b({number_words})\s+({number_words})[\s-]+digit\b",
        lambda match: [
            word_numbers[match.group(1).casefold()],
            word_numbers[match.group(2).casefold()],
        ],
        "quantity",
    )
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
        rf"\b({number_words})\s+(hundred|thousand|million|billion|trillion)\b",
        lambda match: word_numbers[match.group(1).casefold()]
        * magnitudes[match.group(2).casefold()],
        "quantity",
    )
    # Bare English cardinals are numeric only in an explicit quantity phrase.
    # Keeping the unit requirement avoids treating ordinary prose such as
    # ``one thing`` as a factual anchor while covering ``fourteen hours`` and
    # ``twenty years``.
    quantity_units = (
        "years?|months?|weeks?|days?|hours?|minutes?|people|persons?|men|women|"
        "children|workers?|languages|objects|documents|countries|demands|decades?"
    )
    replace(
        rf"\b({number_words})[\s-]+(?:{quantity_units})\b",
        lambda match: word_numbers[match.group(1).casefold()],
        "quantity",
    )
    replace(
        r"\b(thousand|million|billion|trillion)[\s-]+years?\b",
        lambda match: magnitudes[match.group(1).casefold()],
        "quantity",
    )
    replace(
        r"\b(thousands?|hundreds?)\s+of\s+(?:years?|objects?|images|documents|languages)\b",
        lambda match: 1_000 if match.group(1).casefold().startswith("thousand") else 100,
        "quantity",
    )
    replace(
        r"\ba\s+couple\s+of\s+decades\b",
        lambda _match: 20,
        "quantity",
    )
    replace(r"\bfirst\s+decade\b", lambda _match: 10, "quantity")
    replace(
        r"\ba\s+(hundred|thousand|million|billion|trillion)\s+(?:years?|months?|weeks?|days?)\b",
        lambda match: magnitudes[match.group(1).casefold()],
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

    def chinese_tens_value(value: str) -> int:
        if "十" not in value:
            return chinese_number[value]
        tens, ones = value.split("十", 1)
        return (chinese_number[tens] if tens else 1) * 10 + (
            chinese_number[ones] if ones else 0
        )

    chinese_tens = r"(?:[一二三四五六七八九两]?十[一二三四五六七八九]?|[一二三四五六七八九两])"
    replace(
        r"[一二三四五六七八九两]\s*加\s*[一二三四五六七八九两]\s*等于\s*([一二三四五六七八九两])",
        lambda match: chinese_number[match.group(1)],
        "quantity",
    )
    replace_many(
        rf"({chinese_tens})\s*(?:至|到)\s*({chinese_tens})",
        lambda match: [chinese_tens_value(match.group(1)), chinese_tens_value(match.group(2))],
        "quantity",
    )
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
    replace(r"(?<![一二三四五六七八九两数几])十亿", lambda _match: 1_000_000_000, "quantity")
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
    replace_many(
        r"([一二三四五六七八九两])个([一二三四五六七八九])位数",
        lambda match: [chinese_number[match.group(1)], chinese_number[match.group(2)]],
        "quantity",
    )
    replace(
        r"([一二三四五六七八九两])年半",
        lambda match: chinese_number[match.group(1)],
        "quantity",
    )
    # Chinese ``一个/一名/一位`` often supplies a natural singular article
    # where English makes no count claim.  Only treat ``一`` as an anchor for
    # elapsed-time units; other explicit Chinese cardinals remain comparable.
    replace(
        r"(?<!十)一\s*(?:个)?\s*(?:年|日|天|小时|周|星期|个月)",
        lambda _match: 1,
        "quantity",
    )
    replace(
        r"(?<!十)([二三四五六七八九两])\s*(?:个)?\s*(?:年|日|天|小时|周|星期|个月|人|名|项要求)",
        lambda match: chinese_number[match.group(1)],
        "quantity",
    )
    replace(r"头十年", lambda _match: 10, "quantity")
    replace(
        r"(?<![第数几一二三四五六七八九十百千万亿])([一二三四五六七八九两]?)十([一二三四五六七八九]?)(?![百千万亿字分足全余几])",
        lambda match: (chinese_number[match.group(1)] if match.group(1) else 1) * 10
        + (chinese_number[match.group(2)] if match.group(2) else 0),
        "quantity",
    )
    replace_many(
        r"(?<![A-Za-z0-9_.])(?:[$€£¥]\s*)?(\d[\d,]*(?:\.\d+)?)\s*[‒–—-]\s*(?:[$€£¥]\s*)?(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|trillion)\b",
        lambda match: [
            _scaled_number(match.group(1), magnitudes[match.group(3).casefold()]),
            _scaled_number(match.group(2), magnitudes[match.group(3).casefold()]),
        ],
        "quantity",
    )
    replace(
        r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|trillion)\b",
        lambda match: _scaled_number(match.group(1), magnitudes[match.group(2).casefold()]),
        "quantity",
    )
    replace(
        r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)\s*多?\s*(万亿|万|亿)",
        lambda match: _scaled_number(
            match.group(1),
            {"万": 10_000, "亿": 100_000_000, "万亿": 1_000_000_000_000}[
                match.group(2)
            ],
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
    # In bibliography prose, ``May (1973)`` is commonly an author's surname,
    # not a calendar month.  Remove that unambiguous citation form before
    # looking for contextual English month names.
    working = re.sub(r"\bMay\s*\(\d{4}\)", " ", working)
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
