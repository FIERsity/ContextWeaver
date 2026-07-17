"""Provider-neutral chapter and book coherence review adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
import time
from typing import Any, Callable

from .adapters import _retry_after, _retryable


@dataclass(frozen=True)
class ScopeReviewDecision:
    verdict: str
    categories: list[str]
    rationale: str
    confidence: float
    revisions: dict[str, str] = field(default_factory=dict)


class CoherenceReviewAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def review_scope(self, payload: dict[str, Any]) -> ScopeReviewDecision:
        """Review a bounded chapter or book dossier."""


class HeuristicCoherenceReviewAdapter(CoherenceReviewAdapter):
    """Deterministic offline coherence pass used for workflow verification."""

    name = "heuristic-coherence"
    model = "consistency-signals-v1"

    def review_scope(self, payload: dict[str, Any]) -> ScopeReviewDecision:
        translations: dict[str, set[str]] = {}
        for item in payload["evidence"]:
            translations.setdefault(item["source"].casefold(), set()).add(
                item["translation"].casefold()
            )
        inconsistent = sum(1 for values in translations.values() if len(values) > 1)
        categories = ["repeated_source_inconsistent"] if inconsistent else []
        rationale = (
            f"Found {inconsistent} repeated source form(s) with differing translations; "
            "offline review records the signal but does not guess a revision."
            if inconsistent
            else "No deterministic chapter/book coherence issue found."
        )
        return ScopeReviewDecision("pass", categories, rationale, 0.6)


class OpenAICoherenceReviewAdapter(CoherenceReviewAdapter):
    """Optional Agent reviewer for chapter and book consistency."""

    name = "openai-coherence"

    def __init__(
        self,
        model: str = "gpt-5.6-sol",
        *,
        api_key: str | None = None,
        client: Any = None,
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
                raise RuntimeError("OPENAI_API_KEY is required for OpenAI coherence review")
            client = OpenAI(api_key=key)
        self.client = client
        self.model = model
        self.max_retries = max_retries
        self.interval = 60 / requests_per_minute
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None

    def review_scope(self, payload: dict[str, Any]) -> ScopeReviewDecision:
        self._limit()
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["pass", "revise"]},
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "concept_consistency",
                            "terminology_consistency",
                            "entity_consistency",
                            "voice_consistency",
                            "argument_continuity",
                            "cross_section_consistency",
                        ],
                    },
                },
                "rationale": {"type": "string"},
                "confidence": {"type": "number"},
                "revisions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "segment_id": {"type": "string"},
                            "revised_translation": {"type": "string"},
                        },
                        "required": ["segment_id", "revised_translation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["verdict", "categories", "rationale", "confidence", "revisions"],
            "additionalProperties": False,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=(
                        "Review this bounded chapter or book dossier for consistency that isolated segment review cannot detect. "
                        "Use the source as sole semantic authority and the translation strategy as context-sensitive guidance. "
                        "Check concept, terminology, entities, narrative voice, argument continuity, and cross-section consistency. "
                        "Revise only evidence segments whose complete replacement can be justified from the dossier. Never invent text for omitted segments."
                    ),
                    input=json.dumps(payload, ensure_ascii=False),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "coherence_review",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )
                raw = json.loads(response.output_text)
                revisions: dict[str, str] = {}
                for item in raw["revisions"]:
                    segment_id = str(item["segment_id"])
                    if segment_id in revisions:
                        raise ValueError(f"Duplicate coherence revision for {segment_id}")
                    revisions[segment_id] = str(item["revised_translation"])
                return ScopeReviewDecision(
                    "revised" if raw["verdict"] == "revise" else "pass",
                    list(raw["categories"]),
                    str(raw["rationale"]),
                    float(raw["confidence"]),
                    revisions,
                )
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(
                        f"OpenAI coherence review failed after {attempt + 1} attempt(s): {exc}"
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
