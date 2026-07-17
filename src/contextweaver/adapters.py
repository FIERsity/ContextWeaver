"""Provider-neutral translation adapter interface and offline mock."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
import time
from typing import Any, Callable

from .models import ContextPacket


class TranslationAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def translate(self, packet: ContextPacket) -> list[str]:
        """Return exactly one translated string for each source segment."""


class MockTranslationAdapter(TranslationAdapter):
    name = "mock"
    model = "deterministic-copy-v1"

    def translate(self, packet: ContextPacket) -> list[str]:
        return [f"[MOCK] {segment.raw or segment.text}" for segment in packet.source_segments]


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
            "properties": {"translations": {"type": "array", "items": {"type": "string"}, "minItems": len(packet.source_segments), "maxItems": len(packet.source_segments)}},
            "required": ["translations"], "additionalProperties": False,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions="Translate faithfully. Preserve Markdown structure and inline markup. Return exactly one translation per source item. Use context only for disambiguation. Record no commentary.",
                    input=json.dumps(payload, ensure_ascii=False),
                    text={"format": {"type": "json_schema", "name": "segment_translations", "strict": True, "schema": schema}},
                )
                result = json.loads(response.output_text)["translations"]
                return [str(item) for item in result]
            except Exception as exc:
                if attempt >= self.max_retries or not _retryable(exc):
                    raise RuntimeError(f"OpenAI translation failed after {attempt + 1} attempt(s): {exc}") from exc
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
        "source": [{"id": item.id, "markdown": item.raw or item.text} for item in packet.source_segments],
        "previous": packet.previous_text, "next": packet.next_text,
        "section_summary": packet.section_summary,
        "glossary": [item.to_dict() for item in packet.glossary if item.status == "approved"],
        "entities": [item.to_dict() for item in packet.entities if item.status == "approved"],
    }


def _retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return status in {408, 409, 429} or (isinstance(status, int) and status >= 500) or isinstance(exc, (TimeoutError, ConnectionError))


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "headers", {}).get("retry-after") if response else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None

