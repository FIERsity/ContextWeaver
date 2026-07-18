"""Provider-neutral translation adapter interface and offline mock."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import os
import re
import time
from threading import Lock
from typing import Any, Callable

from .models import ContextPacket, TranslationRecord


@dataclass(frozen=True)
class ReviewDecision:
    verdict: str
    categories: list[str]
    rationale: str
    confidence: float
    revised_translation: str | None = None


class ReviewAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def review(
        self, packet: ContextPacket, translations: list[TranslationRecord]
    ) -> list[ReviewDecision]:
        """Critique and optionally revise each source-aligned translation."""


class HeuristicReviewAdapter(ReviewAdapter):
    """Offline deterministic reviewer for workflow verification and known rules."""

    name = "heuristic-review"
    model = "concept-checks-v1"

    def review(
        self, packet: ContextPacket, translations: list[TranslationRecord]
    ) -> list[ReviewDecision]:
        decisions = []
        for segment, record in zip(packet.source_segments, translations, strict=True):
            if "disempowered" in segment.text.casefold() and "失去了力量" in record.translated_text:
                decisions.append(
                    ReviewDecision(
                        "revised",
                        ["concept_role"],
                        "In this political-economic context, disempowered concerns power rather than vague force.",
                        0.98,
                        record.translated_text.replace("失去了力量", "权力遭到削弱"),
                    )
                )
            else:
                decisions.append(ReviewDecision("pass", [], "No deterministic issue found.", 0.6))
        return decisions


class OpenAIReviewAdapter(ReviewAdapter):
    """Optional Agent critic and reviser with pacing and bounded retries."""

    name = "openai-review"

    def __init__(
        self,
        model: str = "gpt-5.6-sol",
        *,
        api_key: str | None = None,
        client: Any = None,
        max_retries: int = 4,
        requests_per_minute: float = 60,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install ContextWeaver with the 'openai' extra") from exc
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY is required for the OpenAI reviewer")
            client = OpenAI(api_key=key)
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.interval = 60 / requests_per_minute
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None
        self._limit_lock = Lock()

    def review(
        self, packet: ContextPacket, translations: list[TranslationRecord]
    ) -> list[ReviewDecision]:
        self._limit()
        count = len(translations)
        schema = {
            "type": "object",
            "properties": {
                "reviews": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "verdict": {"type": "string", "enum": ["pass", "revise"]},
                            "categories": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "semantic_fidelity",
                                        "concept_role",
                                        "terminology",
                                        "natural_zh",
                                        "rhetoric",
                                        "format",
                                    ],
                                },
                            },
                            "rationale": {"type": "string"},
                            "confidence": {"type": "number"},
                            "revised_translation": {"type": ["string", "null"]},
                        },
                        "required": [
                            "verdict",
                            "categories",
                            "rationale",
                            "confidence",
                            "revised_translation",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["reviews"],
            "additionalProperties": False,
        }
        payload = _packet_payload(packet)
        payload["translations"] = [
            {"segment_id": item.segment_id, "translation": item.translated_text}
            for item in translations
        ]
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=(
                        "Act as a conservative translation critic and reviser. Compare every translation with its aligned source, adjacent context, and translation strategy. "
                        "Check semantic fidelity, claim strength, concept sense, terminology, rhetoric, Markdown, and idiomatic zh-CN. "
                        "Return pass when no material change is needed. Return revise only with a complete replacement translation; never add facts or commentary to the translation."
                    ),
                    input=json.dumps(payload, ensure_ascii=False),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "translation_reviews",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )
                raw = json.loads(response.output_text)["reviews"]
                return [
                    ReviewDecision(
                        "revised" if item["verdict"] == "revise" else "pass",
                        list(item["categories"]),
                        str(item["rationale"]),
                        float(item["confidence"]),
                        item["revised_translation"],
                    )
                    for item in raw
                ]
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(
                        f"OpenAI review failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                self.sleep(_retry_after(exc) or min(2**attempt, 30))
        raise AssertionError("unreachable")

    def _limit(self) -> None:
        with self._limit_lock:
            now = self.clock()
            if self._last_request is not None:
                wait = self.interval - (now - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()


class TranslationAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def translate(self, packet: ContextPacket) -> list[str]:
        """Return exactly one translated string for each source segment."""


class _ResponseFormatError(ValueError):
    """A transient provider response that is safe to retry without writing state."""


class OpenAICompatibleChatTranslationAdapter(TranslationAdapter):
    """Chat Completions adapter for OpenAI-compatible providers."""

    name = "openai-compatible-chat"

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        client: Any = None,
        max_retries: int = 4,
        requests_per_minute: float = 60,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for an OpenAI-compatible adapter")
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install ContextWeaver with the 'openai' extra") from exc
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY is required for the compatible adapter")
            client = OpenAI(api_key=key, base_url=base_url)
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.interval = 60 / requests_per_minute
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None
        self._limit_lock = Lock()

    def translate(self, packet: ContextPacket) -> list[str]:
        self._limit()
        payload = _packet_payload(packet)
        instructions = (
            "Translate faithfully into the project's target language. The source items are the "
            "sole semantic authority: never add, omit, soften, strengthen, or change a claim. "
            "Preserve Markdown structure and inline markup. Return exactly one translation per "
            "source item. When targeting zh-CN, write idiomatic Mainland Simplified Chinese and "
            "avoid English-shaped syntax while retaining all facts, qualifications, relations, "
            "tone, and rhetoric. Return JSON only, exactly in this shape: "
            '{"translations":["one translation for each source item in order"]}.'
        )
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    response_format={"type": "json_object"},
                )
                content = (response.choices[0].message.content or "").strip()
                if content.startswith("```json") and content.endswith("```"):
                    content = content.removeprefix("```json").removesuffix("```").strip()
                try:
                    result = json.loads(content or "{}")
                except json.JSONDecodeError as exc:
                    raise _ResponseFormatError("response was not valid JSON") from exc
                translations = result.get("translations")
                if not isinstance(translations, list):
                    raise _ResponseFormatError("response JSON must contain a translations array")
                if len(translations) != len(packet.source_segments):
                    raise _ResponseFormatError("response translation count does not match source items")
                return [
                    _restore_numeric_reference_links(segment.raw or segment.text, str(item))
                    for segment, item in zip(packet.source_segments, translations, strict=True)
                ]
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(
                        f"Compatible chat translation failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                delay = _retry_after(exc) or min(2**attempt, 30)
                self.sleep(delay)
        raise AssertionError("unreachable")

    def _limit(self) -> None:
        with self._limit_lock:
            now = self.clock()
            if self._last_request is not None:
                wait = self.interval - (now - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()


class MockTranslationAdapter(TranslationAdapter):
    name = "mock"
    model = "deterministic-copy-v1"

    def translate(self, packet: ContextPacket) -> list[str]:
        return [f"[MOCK] {segment.raw or segment.text}" for segment in packet.source_segments]


class BibliographyPassthroughAdapter(TranslationAdapter):
    """Preserve scholarly citation metadata when no safe localization exists."""

    name = "bibliography-passthrough"
    model = "source-citation-preservation-v1"

    def translate(self, packet: ContextPacket) -> list[str]:
        return [segment.raw or segment.text for segment in packet.source_segments]


class OpenAITranslationAdapter(TranslationAdapter):
    """Optional Responses API adapter with bounded exponential retry."""

    name = "openai"

    def __init__(
        self,
        model: str = "gpt-5.6-sol",
        *,
        api_key: str | None = None,
        client: Any = None,
        max_retries: int = 4,
        requests_per_minute: float = 60,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install ContextWeaver with the 'openai' extra") from exc
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY is required for the OpenAI adapter")
            client = OpenAI(api_key=key)
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.interval = 60 / requests_per_minute
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None

    def translate(self, packet: ContextPacket) -> list[str]:
        self._limit()
        payload = _packet_payload(packet)
        schema = {
            "type": "object",
            "properties": {
                "translations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": len(packet.source_segments),
                    "maxItems": len(packet.source_segments),
                }
            },
            "required": ["translations"],
            "additionalProperties": False,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions="Translate faithfully into the project's target language. The source items are the sole semantic authority: never add, omit, soften, strengthen, or change a claim to follow a reference translation, and resolve every conflict in favor of the source. Preserve facts, qualifications, argument relations, tone, and important rhetoric. Preserve Markdown structure and inline markup. Return exactly one translation per source item. A human_reference may be provided only as approximate consultation evidence for meaning and terminology; do not assume paragraph alignment or copy regional wording blindly. When targeting zh-CN, write idiomatic Mainland Simplified Chinese: you may reorder clauses, split or combine sentences, restore natural subjects and transitions, and reshape punctuation when meaning and rhetorical force remain unchanged. Avoid English-shaped syntax and sentence-by-sentence calques. Use adjacent context only for disambiguation. Record no commentary.",
                    input=json.dumps(payload, ensure_ascii=False),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "segment_translations",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )
                result = json.loads(response.output_text)["translations"]
                return [str(item) for item in result]
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(
                        f"OpenAI translation failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                delay = _retry_after(exc) or min(2**attempt, 30)
                self.sleep(delay)
        raise AssertionError("unreachable")

    def _limit(self) -> None:
        now = self.clock()
        if self._last_request is not None:
            wait = self.interval - (now - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()


def _packet_payload(packet: ContextPacket) -> dict[str, Any]:
    return {
        "source": [
            {"id": item.id, "markdown": item.raw or item.text} for item in packet.source_segments
        ],
        "source_language": packet.source_language,
        "target_language": packet.target_language,
        "previous": packet.previous_text,
        "next": packet.next_text,
        "section_summary": packet.section_summary,
        "glossary": [item.to_dict() for item in packet.glossary if item.status == "approved"],
        "entities": [item.to_dict() for item in packet.entities if item.status == "approved"],
        "human_reference": packet.reference_texts,
        "translation_strategy": packet.translation_strategy,
    }


_NUMERIC_LINK = re.compile(r"(?<!!)\[(\d+)\]\(([^)]+)\)")
_NUMERIC_REFERENCE = re.compile(r"(?<!!)\[(\d+)\](?!\()")


def _restore_numeric_reference_links(source: str, translation: str) -> str:
    """Restore dropped destinations for numeric Markdown footnote references.

    Some compatible chat providers preserve a visible citation such as ``[66]``
    but omit its retained EPUB destination.  This narrowly restores a source
    destination only when the numeric markers remain in the same order; prose
    links are deliberately left to the model and the structural validator.
    """
    source_links = list(_NUMERIC_LINK.finditer(source))
    if not source_links:
        return translation
    target_markers = list(_NUMERIC_REFERENCE.finditer(translation))
    if len(target_markers) < len(source_links):
        return translation
    restored: list[str] = []
    cursor = 0
    for index, source_link in enumerate(source_links):
        marker = target_markers[index]
        if marker.group(1) != source_link.group(1):
            return translation
        restored.append(translation[cursor : marker.start()])
        restored.append(f"[{marker.group(1)}]({source_link.group(2)})")
        cursor = marker.end()
    restored.append(translation[cursor:])
    return "".join(restored)


def _retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return (
        status in {408, 409, 429}
        or (isinstance(status, int) and status >= 500)
        or isinstance(exc, (TimeoutError, ConnectionError, _ResponseFormatError))
    )


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "headers", {}).get("retry-after") if response else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
