"""Bounded, append-only chapter and whole-book coherence review."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from .coherence_adapters import CoherenceReviewAdapter
from .models import (
    AmbiguityRecord,
    ScopeReview,
    Section,
    SectionSummary,
    Segment,
    TranslationRecord,
    TranslationUnit,
)
from .pipeline import STATE, active_translations, stable_id
from .storage import append_jsonl, read_json, read_jsonl


def review_sections(
    root: Path,
    adapter: CoherenceReviewAdapter,
    section_ids: set[str] | None = None,
) -> tuple[int, int, int]:
    sections, segments, active, units, previous = _state(root)
    known = {item.id for item in sections}
    unknown = (section_ids or set()) - known
    if unknown:
        raise ValueError(f"Unknown section IDs: {sorted(unknown)}")
    targets = [item for item in sections if section_ids is None or item.id in section_ids]
    reviewed = revised = skipped = 0
    for section in targets:
        scoped = [item for item in segments if item.section_id == section.id]
        if not scoped:
            continue
        _require_complete(scoped, active, f"section {section.id}")
        count, changes, was_skipped = _review_scope(
            root, adapter, "section", section.id, section.title, scoped,
            sections, segments, active, units, previous,
        )
        reviewed += count
        revised += changes
        skipped += was_skipped
    return reviewed, revised, skipped


def review_book(root: Path, adapter: CoherenceReviewAdapter) -> tuple[int, int, int]:
    sections, segments, active, units, previous = _state(root)
    _require_complete(segments, active, "book")
    return _review_scope(
        root, adapter, "book", "book", "Complete work", segments,
        sections, segments, active, units, previous,
    )


def _review_scope(
    root: Path,
    adapter: CoherenceReviewAdapter,
    scope_type: str,
    scope_id: str,
    title: str,
    scoped: list[Segment],
    sections: list[Section],
    all_segments: list[Segment],
    active: dict[str, TranslationRecord],
    units: list[TranslationUnit],
    previous: list[ScopeReview],
) -> tuple[int, int, int]:
    review_context = _review_context(root, scoped)
    strategy = review_context["translation_strategy"]
    section_context = review_context["section_summaries"]
    ambiguities = review_context["open_ambiguities"]
    input_digest = _digest(scoped, active, review_context)
    if any(
        item.scope_type == scope_type and item.scope_id == scope_id
        and item.adapter == adapter.name and item.model == adapter.model
        and input_digest in {item.input_digest, item.output_digest}
        for item in previous
    ):
        return 0, 0, 1
    evidence = _dossier(scope_type, scoped, sections, all_segments, active, strategy)
    payload = {
        "scope_type": scope_type, "scope_id": scope_id, "title": title,
        "translation_strategy": strategy, "section_summaries": section_context,
        "open_ambiguities": ambiguities, "evidence": evidence,
    }
    decision = adapter.review_scope(payload)
    if decision.verdict not in {"pass", "revised"}:
        raise RuntimeError(f"Coherence reviewer returned invalid verdict: {decision.verdict}")
    if decision.verdict == "pass" and decision.revisions:
        raise RuntimeError("Coherence reviewer returned revisions with a pass verdict")
    if decision.verdict == "revised" and not decision.revisions:
        raise RuntimeError("Coherence reviewer requested revision without replacements")
    evidence_ids = {item["segment_id"] for item in evidence}
    unknown_revisions = set(decision.revisions) - evidence_ids
    if unknown_revisions:
        raise RuntimeError(
            f"Coherence reviewer revised segments outside its evidence: {sorted(unknown_revisions)}"
        )
    unit_by_segment = {segment_id: unit for unit in units for segment_id in unit.segment_ids}
    output_ids: list[str] = []
    for segment_id, translated_text in decision.revisions.items():
        text = translated_text.strip()
        previous_record = active[segment_id]
        if not text:
            raise RuntimeError(f"Coherence reviewer returned empty revision for {segment_id}")
        if text == previous_record.translated_text.strip():
            raise RuntimeError(f"Coherence reviewer returned unchanged revision for {segment_id}")
        segment = next(item for item in scoped if item.id == segment_id)
        unit = unit_by_segment[segment_id]
        revision = previous_record.revision + 1
        record = TranslationRecord(
            stable_id("tr", unit.id, segment.id, adapter.name, adapter.model, revision),
            unit.id, segment.id, text, adapter.name, adapter.model,
            "review-v2-section-coherence" if scope_type == "section" else "review-v3-book-coherence",
            datetime.now(timezone.utc).isoformat(), hashlib.sha256(segment.text.encode()).hexdigest(),
            "completed", revision, previous_record.id,
            f"agent-{scope_type}-review:" + (",".join(decision.categories) or "general"),
        )
        append_jsonl(root / STATE / "translations.jsonl", record)
        active[segment_id] = record
        output_ids.append(record.id)
    output_digest = _digest(scoped, active, review_context)
    review = ScopeReview(
        stable_id("scope_review", scope_type, scope_id, input_digest, adapter.name, adapter.model),
        scope_type, scope_id, input_digest, output_digest, adapter.name, adapter.model,
        datetime.now(timezone.utc).isoformat(), decision.verdict, list(decision.categories),
        decision.rationale, max(0.0, min(1.0, float(decision.confidence))),
        [item["segment_id"] for item in evidence], output_ids,
    )
    append_jsonl(root / STATE / "scope_reviews.jsonl", review)
    previous.append(review)
    return 1, len(output_ids), 0


def _state(root: Path) -> tuple[
    list[Section], list[Segment], dict[str, TranslationRecord],
    list[TranslationUnit], list[ScopeReview],
]:
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    return (
        sections, segments, active_translations(records),
        read_jsonl(root / STATE / "units.jsonl", TranslationUnit),
        read_jsonl(root / STATE / "scope_reviews.jsonl", ScopeReview),
    )


def _require_complete(
    segments: list[Segment], active: dict[str, TranslationRecord], label: str
) -> None:
    missing = [item.id for item in segments if item.id not in active]
    if missing:
        raise RuntimeError(
            f"Cannot run coherence review for {label}: {len(missing)} translation(s) missing"
        )


def _digest(
    segments: list[Segment],
    active: dict[str, TranslationRecord],
    context: dict[str, Any] | None = None,
) -> str:
    value = "\x1f".join(active[item.id].id for item in segments)
    if context:
        import json

        value += "\x1e" + json.dumps(context, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def scope_fingerprint(root: Path, segments: list[Segment]) -> str | None:
    """Return the current review fingerprint, or ``None`` when translation is incomplete."""
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    active = active_translations(records)
    if any(item.id not in active for item in segments):
        return None
    return _digest(segments, active, _review_context(root, segments))


def _review_context(root: Path, scoped: list[Segment]) -> dict[str, Any]:
    strategy_path = root / STATE / "translation_brief.json"
    strategy = read_json(strategy_path) if strategy_path.exists() else {}
    from .summaries import active_section_summaries

    summaries = active_section_summaries(
        read_jsonl(root / STATE / "section_summaries.jsonl", SectionSummary)
    )
    relevant_sections = {item.section_id for item in scoped}
    section_context = {
        section_id: summaries[section_id].summary
        for section_id in relevant_sections if section_id in summaries
    }
    ambiguities = [
        item.to_dict() for item in read_jsonl(
            root / STATE / "ambiguities.jsonl", AmbiguityRecord
        )
        if item.section_id in relevant_sections and item.status == "open"
    ]
    return {
        "translation_strategy": strategy,
        "section_summaries": section_context,
        "open_ambiguities": ambiguities,
    }


def _dossier(
    scope_type: str,
    scoped: list[Segment],
    sections: list[Section],
    all_segments: list[Segment],
    active: dict[str, TranslationRecord],
    strategy: dict[str, Any],
    max_chars: int = 60_000,
) -> list[dict[str, str]]:
    if scope_type == "section":
        candidates = _stratified(scoped, strategy)
    else:
        candidates = []
        by_section = {section.id: [] for section in sections}
        for segment in all_segments:
            by_section.setdefault(segment.section_id, []).append(segment)
        for section in sections:
            items = by_section.get(section.id, [])
            if items:
                candidates.extend([items[0], items[len(items) // 2], items[-1]])
        candidates.extend(_concept_hits(scoped, strategy, limit_per_term=8))
    unique = {item.id: item for item in candidates}
    ordered = sorted(unique.values(), key=lambda item: item.ordinal)
    section_titles = {item.id: item.title for item in sections}
    evidence: list[dict[str, str]] = []
    used = 0
    for segment in ordered:
        translation = active[segment.id].translated_text
        cost = len(segment.text) + len(translation)
        if evidence and used + cost > max_chars:
            continue
        evidence.append({
            "segment_id": segment.id, "section_id": segment.section_id,
            "section_title": section_titles.get(segment.section_id, ""),
            "source": segment.text, "translation": translation,
        })
        used += cost
    return evidence


def _stratified(segments: list[Segment], strategy: dict[str, Any]) -> list[Segment]:
    if len(segments) <= 40:
        return segments
    indexes = {0, len(segments) - 1}
    indexes.update(round(position * (len(segments) - 1) / 29) for position in range(30))
    selected = [segments[index] for index in sorted(indexes)]
    selected.extend(_concept_hits(segments, strategy, limit_per_term=8))
    return selected


def _concept_hits(
    segments: list[Segment], strategy: dict[str, Any], limit_per_term: int
) -> list[Segment]:
    selected: list[Segment] = []
    for rule in strategy.get("concept_rules", []):
        term = str(rule.get("source_term", "")).casefold()
        if not term:
            continue
        hits = [item for item in segments if term in item.text.casefold()]
        selected.extend(hits[:limit_per_term])
    return selected
