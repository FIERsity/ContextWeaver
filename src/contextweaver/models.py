"""Transparent domain records used by the translation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Status = Literal["pending", "completed", "failed", "needs_review"]


class Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Project(Record):
    id: str
    name: str
    source_language: str
    target_language: str
    schema_version: int = 1


@dataclass(frozen=True)
class SourceDocument(Record):
    id: str
    project_id: str
    title: str
    source_path: str
    media_type: str
    sha256: str
    original_path: str | None = None
    source_format: str = "markdown"


@dataclass(frozen=True)
class Section(Record):
    id: str
    document_id: str
    title: str
    level: int
    ordinal: int


@dataclass(frozen=True)
class Segment(Record):
    id: str
    document_id: str
    section_id: str
    ordinal: int
    text: str
    kind: str = "paragraph"
    raw: str = ""
    format_signature: list[str] = field(default_factory=list)
    source_locator: str = ""


@dataclass(frozen=True)
class TranslationUnit(Record):
    id: str
    section_id: str
    segment_ids: list[str]
    ordinal: int


@dataclass(frozen=True)
class GlossaryEntry(Record):
    term: str
    preferred_translation: str
    allowed_variants: list[str] = field(default_factory=list)
    note: str = ""
    source_segment_id: str | None = None
    confidence: float = 1.0
    evidence_segment_ids: list[str] = field(default_factory=list)
    status: Literal["proposed", "approved", "rejected"] = "approved"


@dataclass(frozen=True)
class Entity(Record):
    id: str
    name: str
    kind: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    evidence_segment_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    status: Literal["proposed", "approved", "rejected"] = "approved"


@dataclass(frozen=True)
class ContextPacket(Record):
    unit_id: str
    source_segments: list[Segment]
    previous_text: str | None
    next_text: str | None
    section_summary: str | None
    glossary: list[GlossaryEntry]
    entities: list[Entity]


@dataclass(frozen=True)
class TranslationRecord(Record):
    id: str
    unit_id: str
    segment_id: str
    translated_text: str
    adapter: str
    model: str
    prompt_version: str
    created_at: str
    source_sha256: str
    status: Status = "completed"
    revision: int = 1
    supersedes: str | None = None
    reason: str = "initial"


@dataclass(frozen=True)
class ReviewIssue(Record):
    id: str
    kind: str
    message: str
    segment_id: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    status: Literal["open", "resolved"] = "open"


@dataclass(frozen=True)
class Manifest(Record):
    schema_version: int
    project_id: str
    source_sha256: str | None
    section_count: int
    segment_count: int
    unit_count: int
    translation_count: int
    steps: dict[str, Status]
