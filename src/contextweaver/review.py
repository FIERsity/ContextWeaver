"""Append-only Agent criticism and revision workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from .adapters import ReviewAdapter
from .models import ContextPacket, Segment, TranslationRecord, TranslationReview, TranslationUnit
from .pipeline import STATE, active_translations, build_context, stable_id
from .storage import append_jsonl, read_jsonl


def review_project(
    root: Path,
    adapter: ReviewAdapter,
    segment_ids: set[str] | None = None,
    section_ids: set[str] | None = None,
) -> tuple[int, int, int]:
    """Review active translations once, appending revisions only when needed.

    Returns ``(reviewed, revised, skipped)``. A review marks both its input and
    output TranslationRecord IDs as processed, making retries idempotent.
    """
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    units = read_jsonl(root / STATE / "units.jsonl", TranslationUnit)
    records = read_jsonl(root / STATE / "translations.jsonl", TranslationRecord)
    reviews = read_jsonl(root / STATE / "reviews.jsonl", TranslationReview)
    if not records:
        raise RuntimeError("No completed translations. Run translate before review.")
    known_segment_ids = {item.id for item in segments}
    unknown = (segment_ids or set()) - known_segment_ids
    if unknown:
        raise ValueError(f"Unknown segment IDs: {sorted(unknown)}")
    known_section_ids = {item.section_id for item in segments}
    unknown_sections = (section_ids or set()) - known_section_ids
    if unknown_sections:
        raise ValueError(f"Unknown section IDs: {sorted(unknown_sections)}")
    selected = set(segment_ids or set())
    if section_ids:
        selected.update(item.id for item in segments if item.section_id in section_ids)
    selected_or_all = selected if segment_ids or section_ids else known_segment_ids
    active = active_translations(records)
    reviewed_record_ids = {
        record_id
        for review in reviews
        for record_id in (review.input_translation_id, review.output_translation_id)
    }
    reviewed = revised = skipped = 0
    for unit in units:
        packet = build_context(root, unit)
        pending_segments = [
            segment
            for segment in packet.source_segments
            if segment.id in selected_or_all
            and segment.id in active
            and active[segment.id].id not in reviewed_record_ids
        ]
        skipped += sum(
            1
            for segment in packet.source_segments
            if segment.id in selected_or_all
            and segment.id in active
            and active[segment.id].id in reviewed_record_ids
        )
        if not pending_segments:
            continue
        structural_segments = [
            segment
            for segment in pending_segments
            if active[segment.id].adapter == "structural-passthrough"
        ]
        for segment in structural_segments:
            previous = active[segment.id]
            review = TranslationReview(
                stable_id(
                    "review",
                    segment.id,
                    previous.id,
                    "structural-validator",
                    "deterministic-v1",
                ),
                segment.id,
                previous.id,
                previous.id,
                "structural-validator",
                "deterministic-v1",
                datetime.now(timezone.utc).isoformat(),
                "pass",
                ["format"],
                "Source-only structure is preserved exactly; semantic review is not applicable.",
                1.0,
            )
            append_jsonl(root / STATE / "reviews.jsonl", review)
            reviewed_record_ids.add(previous.id)
            reviewed += 1
        pending_segments = [
            segment for segment in pending_segments if segment not in structural_segments
        ]
        if not pending_segments:
            continue
        pending_packet = ContextPacket(
            unit.id,
            pending_segments,
            packet.previous_text,
            packet.next_text,
            packet.section_summary,
            packet.glossary,
            packet.entities,
            packet.reference_texts,
            packet.source_language,
            packet.target_language,
            packet.translation_strategy,
        )
        inputs = [active[segment.id] for segment in pending_segments]
        decisions = adapter.review(pending_packet, inputs)
        if len(decisions) != len(inputs):
            raise RuntimeError(
                f"Reviewer returned {len(decisions)} decisions for {len(inputs)} translations"
            )
        for segment, previous, decision in zip(pending_segments, inputs, decisions, strict=True):
            if decision.verdict not in {"pass", "revised"}:
                raise RuntimeError(f"Reviewer returned invalid verdict: {decision.verdict}")
            confidence = max(0.0, min(1.0, float(decision.confidence)))
            output = previous
            if decision.verdict == "revised":
                text = (decision.revised_translation or "").strip()
                if not text:
                    raise RuntimeError(
                        f"Reviewer requested revision without replacement for {segment.id}"
                    )
                if text == previous.translated_text.strip():
                    raise RuntimeError(f"Reviewer returned an unchanged revision for {segment.id}")
                revision = previous.revision + 1
                output = TranslationRecord(
                    stable_id("tr", unit.id, segment.id, adapter.name, adapter.model, revision),
                    unit.id,
                    segment.id,
                    text,
                    adapter.name,
                    adapter.model,
                    "review-v1-agent-critic-reviser",
                    datetime.now(timezone.utc).isoformat(),
                    hashlib.sha256(segment.text.encode()).hexdigest(),
                    "completed",
                    revision,
                    previous.id,
                    "agent-review:" + (",".join(decision.categories) or "general"),
                )
                append_jsonl(root / STATE / "translations.jsonl", output)
                active[segment.id] = output
                revised += 1
            review = TranslationReview(
                stable_id("review", segment.id, previous.id, adapter.name, adapter.model),
                segment.id,
                previous.id,
                output.id,
                adapter.name,
                adapter.model,
                datetime.now(timezone.utc).isoformat(),
                decision.verdict,
                list(decision.categories),
                decision.rationale,
                confidence,
            )
            append_jsonl(root / STATE / "reviews.jsonl", review)
            reviewed_record_ids.update({previous.id, output.id})
            reviewed += 1
    return reviewed, revised, skipped
