"""Provider-neutral chapter summarization and ambiguity extraction adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
import time
from typing import Any, Callable

from .adapters import _retry_after, _retryable


@dataclass(frozen=True)
class AmbiguityDecision:
    category: str
    description: str
    evidence_segment_ids: list[str]
    confidence: float


@dataclass(frozen=True)
class SummaryDecision:
    summary: str
    key_points: list[str]
    evidence_segment_ids: list[str]
    confidence: float
    ambiguities: list[AmbiguityDecision] = field(default_factory=list)


class SummaryAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def summarize(self, payload: dict[str, Any]) -> SummaryDecision:
        """Summarize one bounded Section dossier and surface uncertainty."""


class HeuristicSummaryAdapter(SummaryAdapter):
    """Deterministic offline summary for workflow verification."""

    name = "heuristic-summary"
    model = "extractive-v2"

    def summarize(self, payload: dict[str, Any]) -> SummaryDecision:
        evidence = payload["evidence"]
        if not evidence:
            raise RuntimeError("Cannot summarize an empty Section")
        chosen = [evidence[0]]
        if len(evidence) > 2:
            chosen.append(evidence[len(evidence) // 2])
        if len(evidence) > 1:
            chosen.append(evidence[-1])
        summary = _truncate(" ".join(item["source"] for item in chosen), 1200)
        ambiguities = []
        for item in evidence:
            if "[?]" in item["source"] or "[unclear]" in item["source"].casefold():
                ambiguities.append(AmbiguityDecision(
                    "source", "Source contains an explicit uncertainty marker.",
                    [item["segment_id"]], 0.95,
                ))
        return SummaryDecision(
            summary, [_truncate(item["source"], 240) for item in chosen],
            [item["segment_id"] for item in chosen], 0.6, ambiguities,
        )


class OpenAISummaryAdapter(SummaryAdapter):
    """Optional Agent chapter summarizer using structured output."""

    name = "openai-summary"

    def __init__(
        self,
        model: str = "gpt-5.6-sol",
        *,
        client: Any = None,
        api_key: str | None = None,
        max_retries: int = 4,
        requests_per_minute: float = 30,
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
                raise RuntimeError("OPENAI_API_KEY is required for OpenAI summaries")
            client = OpenAI(api_key=key)
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.interval = 60 / requests_per_minute
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None

    def summarize(self, payload: dict[str, Any]) -> SummaryDecision:
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_points": {"type": "array", "items": {"type": "string"}},
                "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
                "ambiguities": {"type": "array", "items": {"type": "object", "properties": {
                    "category": {"type": "string", "enum": [
                        "reference", "term", "entity", "source", "rhetoric", "other"
                    ]},
                    "description": {"type": "string"},
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                }, "required": ["category", "description", "evidence_segment_ids", "confidence"],
                    "additionalProperties": False}},
            },
            "required": [
                "summary", "key_points", "evidence_segment_ids", "confidence", "ambiguities"
            ],
            "additionalProperties": False,
        }
        self._limit()
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=(
                        "Summarize this Section before translation using only the source evidence. Write the summary in the project's target language when practical. "
                        "Capture the argument, narrative movement, tone, and high-impact concepts, not sentence-by-sentence detail. "
                        "Record genuine unresolved references, terms, entities, source defects, or rhetoric as ambiguities; do not invent uncertainty and do not require human approval."
                    ),
                    input=json.dumps(payload, ensure_ascii=False),
                    text={"format": {"type": "json_schema", "name": "section_summary", "strict": True, "schema": schema}},
                )
                raw = json.loads(response.output_text)
                return SummaryDecision(
                    str(raw["summary"]), list(raw["key_points"]),
                    list(raw["evidence_segment_ids"]), float(raw["confidence"]),
                    [AmbiguityDecision(
                        str(item["category"]), str(item["description"]),
                        list(item["evidence_segment_ids"]), float(item["confidence"]),
                    ) for item in raw["ambiguities"]],
                )
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(
                        f"OpenAI summary failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                self.sleep(_retry_after(exc) or min(2**attempt, 30))
        raise AssertionError("unreachable")

    def _limit(self) -> None:
        now = self.clock()
        if self._last_request is not None:
            wait = self.interval - (now - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()


def _truncate(text: str, limit: int) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    head = value[:limit]
    boundaries = [head.rfind(mark) for mark in ("。", "！", "？", ". ", "! ", "? ")]
    boundary = max(boundaries)
    if boundary >= limit // 2:
        return head[: boundary + 1].strip()
    word = head.rfind(" ")
    return head[:word].strip() if word >= limit // 2 else head.strip()
