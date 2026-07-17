"""Resumable Section summaries and conservative ambiguity records."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .models import AmbiguityRecord, Project, Section, SectionSummary, Segment
from .pipeline import STATE, stable_id
from .storage import append_jsonl, read_json, read_jsonl
from .summary_adapters import SummaryAdapter


def summarize_project(
    root: Path,
    adapter: SummaryAdapter,
    section_ids: set[str] | None = None,
    *,
    refresh: bool = False,
) -> tuple[int, int, int]:
    project = Project(**read_json(root / "project.json"))
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    summaries = read_jsonl(root / STATE / "section_summaries.jsonl", SectionSummary)
    ambiguities = read_jsonl(root / STATE / "ambiguities.jsonl", AmbiguityRecord)
    known = {item.id for item in sections}
    unknown = (section_ids or set()) - known
    if unknown:
        raise ValueError(f"Unknown section IDs: {sorted(unknown)}")
    strategy_path = root / STATE / "translation_brief.json"
    strategy = read_json(strategy_path) if strategy_path.exists() else {}
    active = active_section_summaries(summaries)
    known_ambiguities = {item.id for item in ambiguities}
    generated = ambiguity_count = skipped = 0
    for section in sections:
        if section_ids is not None and section.id not in section_ids:
            continue
        scoped = [item for item in segments if item.section_id == section.id]
        if not scoped:
            continue
        digest = _digest(scoped, strategy)
        previous = active.get(section.id)
        if (
            not refresh
            and previous
            and previous.source_digest == digest
            and previous.adapter == adapter.name
            and previous.model == adapter.model
        ):
            skipped += 1
            continue
        evidence = _evidence(scoped, strategy)
        payload = {
            "project": project.to_dict(),
            "section": section.to_dict(),
            "translation_strategy": strategy,
            "evidence": [{"segment_id": item.id, "source": item.text} for item in evidence],
        }
        decision = adapter.summarize(payload)
        summary = decision.summary.strip()
        if not summary:
            raise RuntimeError(f"Summary adapter returned empty output for {section.id}")
        evidence_ids = {item.id for item in evidence}
        unknown_evidence = set(decision.evidence_segment_ids) - evidence_ids
        if unknown_evidence:
            raise RuntimeError(
                f"Summary cites segments outside its evidence: {sorted(unknown_evidence)}"
            )
        revision = previous.revision + 1 if previous else 1
        record = SectionSummary(
            stable_id("summary", section.id, digest, adapter.name, adapter.model, revision),
            section.id,
            digest,
            summary,
            list(decision.key_points),
            list(decision.evidence_segment_ids),
            adapter.name,
            adapter.model,
            datetime.now(timezone.utc).isoformat(),
            max(0.0, min(1.0, float(decision.confidence))),
            revision,
            previous.id if previous else None,
        )
        append_jsonl(root / STATE / "section_summaries.jsonl", record)
        active[section.id] = record
        generated += 1
        for item in decision.ambiguities:
            cited = set(item.evidence_segment_ids)
            if not cited or cited - evidence_ids:
                raise RuntimeError(
                    f"Ambiguity for {section.id} must cite only supplied evidence segments"
                )
            ambiguity = AmbiguityRecord(
                stable_id(
                    "ambiguity",
                    section.id,
                    item.category,
                    item.description,
                    *sorted(item.evidence_segment_ids),
                ),
                section.id,
                item.category,
                item.description,
                list(item.evidence_segment_ids),
                max(0.0, min(1.0, float(item.confidence))),
            )
            if ambiguity.id not in known_ambiguities:
                append_jsonl(root / STATE / "ambiguities.jsonl", ambiguity)
                known_ambiguities.add(ambiguity.id)
                ambiguity_count += 1
    _write_notes(root, sections, active)
    return generated, ambiguity_count, skipped


def active_section_summaries(records: list[SectionSummary]) -> dict[str, SectionSummary]:
    active: dict[str, SectionSummary] = {}
    for record in records:
        if record.section_id not in active or record.revision > active[record.section_id].revision:
            active[record.section_id] = record
    return active


def _digest(segments: list[Segment], strategy: dict[str, Any]) -> str:
    value = "\x1f".join(item.id for item in segments)
    value += "\x1e" + json.dumps(strategy, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def _evidence(
    segments: list[Segment], strategy: dict[str, Any], max_chars: int = 60_000
) -> list[Segment]:
    if sum(len(item.text) for item in segments) <= max_chars:
        return segments
    indexes = {0, len(segments) - 1}
    indexes.update(round(position * (len(segments) - 1) / 29) for position in range(30))
    candidates = [segments[index] for index in sorted(indexes)]
    for rule in strategy.get("concept_rules", []):
        term = str(rule.get("source_term", "")).casefold()
        candidates.extend([item for item in segments if term and term in item.text.casefold()][:8])
    unique = sorted({item.id: item for item in candidates}.values(), key=lambda item: item.ordinal)
    selected: list[Segment] = []
    used = 0
    for item in unique:
        if selected and used + len(item.text) > max_chars:
            continue
        selected.append(item)
        used += len(item.text)
    return selected


def _write_notes(root: Path, sections: list[Section], active: dict[str, SectionSummary]) -> None:
    lines = ["# Section summaries", "", "> Generated automatically; human editing is optional.", ""]
    for section in sections:
        summary = active.get(section.id)
        if summary is None:
            continue
        lines.extend(
            [
                f"## {section.title}",
                "",
                summary.summary,
                "",
                f"- Confidence: {summary.confidence}",
                f"- Evidence: {', '.join(summary.evidence_segment_ids)}",
                "",
            ]
        )
    path = root / "notes" / "section_summaries.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
