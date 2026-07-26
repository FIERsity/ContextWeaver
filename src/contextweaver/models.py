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
class TerminologyCandidate(Record):
    """A candidate rendering backed by a traceable external terminology source."""

    id: str
    term: str
    candidate_translation: str
    authority: Literal["standard", "official", "academic", "publisher", "community"]
    source_title: str
    source_url: str
    source_excerpt: str
    evidence_segment_ids: list[str]
    confidence: float


@dataclass(frozen=True)
class TerminologyDecision(Record):
    """Append-only selection of one candidate without replacing glossary history."""

    id: str
    term: str
    selected_candidate_id: str
    selected_translation: str
    status: Literal["proposed", "approved"]
    rationale: str
    evidence_segment_ids: list[str]


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
    reference_texts: list[str] = field(default_factory=list)
    source_language: str = ""
    target_language: str = ""
    translation_strategy: dict[str, Any] = field(default_factory=dict)


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
class SectionTitleRecord(Record):
    id: str
    section_id: str
    translated_title: str
    adapter: str
    model: str
    created_at: str
    source_sha256: str
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
class AuditResolution(Record):
    """An evidence-backed disposition for one current deterministic issue."""

    id: str
    segment_id: str
    translation_record_id: str
    issue_id: str
    disposition: Literal["source_backed"]
    rationale: str
    evidence: str
    reviewer: str
    model: str
    created_at: str


@dataclass(frozen=True)
class TranslationReview(Record):
    id: str
    segment_id: str
    input_translation_id: str
    output_translation_id: str
    adapter: str
    model: str
    created_at: str
    verdict: Literal["pass", "revised"]
    categories: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class ScopeReview(Record):
    id: str
    scope_type: Literal["section", "book"]
    scope_id: str
    input_digest: str
    output_digest: str
    adapter: str
    model: str
    created_at: str
    verdict: Literal["pass", "revised"]
    categories: list[str] = field(default_factory=list)
    rationale: str = ""
    confidence: float = 1.0
    evidence_segment_ids: list[str] = field(default_factory=list)
    revised_translation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SectionSummary(Record):
    id: str
    section_id: str
    source_digest: str
    summary: str
    key_points: list[str]
    evidence_segment_ids: list[str]
    adapter: str
    model: str
    created_at: str
    confidence: float = 1.0
    revision: int = 1
    supersedes: str | None = None


@dataclass(frozen=True)
class AmbiguityRecord(Record):
    id: str
    section_id: str
    category: Literal["reference", "term", "entity", "source", "rhetoric", "other"]
    description: str
    evidence_segment_ids: list[str]
    confidence: float
    status: Literal["open", "resolved"] = "open"
    resolution: str = ""


@dataclass(frozen=True)
class ReferenceAlignment(Record):
    source_section_id: str
    reference_section_id: str
    chapter_key: str
    confidence: float
    method: str = "chapter-key"


@dataclass(frozen=True)
class LocaleAdaptation(Record):
    reference_segment_id: str
    source_text: str
    adapted_text: str
    converter: str
    status: Literal["draft", "approved", "rejected"] = "draft"


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
