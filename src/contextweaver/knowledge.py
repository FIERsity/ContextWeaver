"""Conservative, evidence-backed terminology and entity proposals."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from .models import Entity, GlossaryEntry, Segment
from .pipeline import STATE, stable_id
from .storage import read_jsonl, write_jsonl


def propose_knowledge(root: Path, minimum_occurrences: int = 2) -> tuple[list[GlossaryEntry], list[Entity]]:
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    evidence: dict[str, list[str]] = defaultdict(list)
    pattern = re.compile(r"\b(?:[A-Z][a-z]{2,})(?:\s+[A-Z][a-z]{2,}){0,3}\b")
    ignored = {"The", "This", "That", "Chapter", "Part", "Inside"}
    for segment in segments:
        for candidate in pattern.findall(segment.text):
            if candidate not in ignored and segment.id not in evidence[candidate]:
                evidence[candidate].append(segment.id)
    selected = {term: ids for term, ids in evidence.items() if len(ids) >= minimum_occurrences}
    existing_glossary = _read_glossary(root / STATE / "glossary.csv")
    existing_entities = read_jsonl(root / STATE / "entities.jsonl", Entity)
    known_terms = {entry.term.casefold() for entry in existing_glossary}
    known_entities = {entry.name.casefold() for entry in existing_entities}
    glossary = existing_glossary + [GlossaryEntry(term, "", [], "Candidate extracted from repeated source usage", ids[0], min(0.9, 0.5 + len(ids) * 0.1), ids, "proposed") for term, ids in sorted(selected.items()) if term.casefold() not in known_terms]
    entities = existing_entities + [Entity(stable_id("ent", term), term, "unknown", "Candidate entity; classify during review", [], ids, min(0.9, 0.5 + len(ids) * 0.1), "proposed") for term, ids in sorted(selected.items()) if term.casefold() not in known_entities]
    _write_glossary(root / STATE / "glossary.csv", glossary)
    write_jsonl(root / STATE / "entities.jsonl", entities)
    return glossary, entities


def _write_glossary(path: Path, entries: list[GlossaryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["term", "preferred_translation", "allowed_variants", "note", "source_segment_id", "confidence", "evidence_segment_ids", "status"])
        for entry in entries:
            writer.writerow([entry.term, entry.preferred_translation, "|".join(entry.allowed_variants), entry.note, entry.source_segment_id or "", entry.confidence, "|".join(entry.evidence_segment_ids), entry.status])


def _read_glossary(path: Path) -> list[GlossaryEntry]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [GlossaryEntry(
            row["term"], row["preferred_translation"],
            [item for item in row["allowed_variants"].split("|") if item], row["note"],
            row["source_segment_id"] or None, float(row["confidence"] or 1),
            [item for item in row.get("evidence_segment_ids", "").split("|") if item],
            row.get("status", "approved") or "approved",
        ) for row in csv.DictReader(handle) if row["term"]]
