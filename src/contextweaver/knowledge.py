"""Conservative, evidence-backed terminology and entity proposals."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .models import Entity, GlossaryEntry, Segment, TerminologyCandidate, TerminologyDecision
from .pipeline import STATE, stable_id
from .storage import append_jsonl, read_jsonl, write_jsonl

_AUTHORITY_RANK = {"standard": 5, "official": 4, "academic": 3, "publisher": 2, "community": 1}


def import_terminology_candidates(root: Path, source: Path) -> tuple[int, int]:
    """Append verified terminology candidates from a strict JSONL interchange file."""
    segments = {item.id for item in read_jsonl(root / STATE / "segments.jsonl", Segment)}
    existing = {item.id for item in read_jsonl(root / STATE / "terminology_candidates.jsonl", TerminologyCandidate)}
    written = skipped = 0
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        expected = {
            "term", "candidate_translation", "authority", "source_title", "source_url",
            "source_excerpt", "evidence_segment_ids", "confidence",
        }
        if set(raw) != expected:
            raise ValueError(f"{source}:{line_number}: expected exactly {sorted(expected)}")
        authority = raw["authority"]
        if authority not in _AUTHORITY_RANK:
            raise ValueError(f"{source}:{line_number}: unsupported authority {authority!r}")
        if not isinstance(raw["evidence_segment_ids"], list) or not raw["evidence_segment_ids"]:
            raise ValueError(f"{source}:{line_number}: evidence_segment_ids must be a non-empty list")
        if unknown := set(raw["evidence_segment_ids"]) - segments:
            raise ValueError(f"{source}:{line_number}: unknown evidence segments {sorted(unknown)}")
        if not all(isinstance(raw[key], str) and raw[key].strip() for key in expected - {"evidence_segment_ids", "confidence", "authority"}):
            raise ValueError(f"{source}:{line_number}: textual fields must be non-empty strings")
        if not raw["source_url"].startswith("https://"):
            raise ValueError(f"{source}:{line_number}: source_url must use https://")
        confidence = float(raw["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError(f"{source}:{line_number}: confidence must be between 0 and 1")
        candidate = TerminologyCandidate(
            stable_id("termcand", *(raw[key] for key in sorted(expected))),
            raw["term"].strip(), raw["candidate_translation"].strip(), authority,
            raw["source_title"].strip(), raw["source_url"].strip(), raw["source_excerpt"].strip(),
            list(raw["evidence_segment_ids"]), confidence,
        )
        if candidate.id in existing:
            skipped += 1
            continue
        append_jsonl(root / STATE / "terminology_candidates.jsonl", candidate)
        existing.add(candidate.id)
        written += 1
    return written, skipped


def adjudicate_terminology(root: Path, approve_authoritative: bool = False) -> tuple[int, int]:
    """Select highest-ranked sourced candidates, preserving every existing glossary row."""
    candidates = read_jsonl(root / STATE / "terminology_candidates.jsonl", TerminologyCandidate)
    existing_glossary = _read_glossary(root / STATE / "glossary.csv")
    existing_terms = {item.term.casefold() for item in existing_glossary}
    existing_decisions = {item.id for item in read_jsonl(root / STATE / "terminology_decisions.jsonl", TerminologyDecision)}
    grouped: dict[str, list[TerminologyCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.term.casefold()].append(candidate)
    additions: list[GlossaryEntry] = []
    written = skipped = 0
    for key, items in sorted(grouped.items()):
        selected = max(items, key=lambda item: (_AUTHORITY_RANK[item.authority], item.confidence, item.id))
        automatic = approve_authoritative and selected.authority in {"standard", "official"} and selected.confidence >= 0.9
        status = "approved" if automatic else "proposed"
        digest = hashlib.sha256("|".join(sorted(item.id for item in items)).encode()).hexdigest()
        decision = TerminologyDecision(
            stable_id("termdec", key, digest, status), selected.term, selected.id,
            selected.candidate_translation, status,
            f"Selected {selected.authority} source '{selected.source_title}' by authority tier and confidence.",
            selected.evidence_segment_ids,
        )
        if decision.id not in existing_decisions:
            append_jsonl(root / STATE / "terminology_decisions.jsonl", decision)
            existing_decisions.add(decision.id)
            written += 1
        else:
            skipped += 1
        if key not in existing_terms:
            additions.append(GlossaryEntry(
                selected.term, selected.candidate_translation, [],
                f"Terminology decision {decision.id}; source: {selected.source_title} ({selected.source_url})",
                selected.evidence_segment_ids[0], selected.confidence,
                selected.evidence_segment_ids, status,
            ))
            existing_terms.add(key)
    if additions:
        _write_glossary(root / STATE / "glossary.csv", existing_glossary + additions)
    return written, skipped


def export_terminology_research_plan(root: Path, output: Path, force: bool = False) -> int:
    """Write bounded, source-evidenced research tasks for an Agent or terminology service."""
    if output.exists() and not force:
        raise FileExistsError(f"Terminology research plan already exists: {output}; pass --force")
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    known = {item.id: item for item in segments}
    glossary = _read_glossary(root / STATE / "glossary.csv")
    strategy_path = root / STATE / "translation_brief.json"
    strategy = json.loads(strategy_path.read_text(encoding="utf-8")) if strategy_path.exists() else {}
    tasks: dict[str, dict[str, object]] = {}
    for entry in glossary:
        if entry.status == "approved" or not entry.term.strip():
            continue
        tasks[entry.term.casefold()] = {
            "term": entry.term,
            "evidence_segment_ids": entry.evidence_segment_ids,
        }
    for rule in strategy.get("concept_rules", []):
        term = str(rule.get("source_term", "")).strip()
        evidence = rule.get("evidence_segment_ids", [])
        if term and isinstance(evidence, list):
            tasks.setdefault(term.casefold(), {"term": term, "evidence_segment_ids": evidence})
    rows = []
    for item in sorted(tasks.values(), key=lambda value: str(value["term"]).casefold()):
        evidence_ids = [
            item_id
            for item_id in item["evidence_segment_ids"]
            if item_id in known and known[item_id].kind in {"paragraph", "blockquote"}
        ]
        if not evidence_ids:
            continue
        rows.append(
            {
                "term": item["term"],
                "source_language": _project_language(root, "source_language"),
                "target_language": _project_language(root, "target_language"),
                "domains": strategy.get("domains", []),
                "evidence": [
                    {"segment_id": item_id, "source_text": known[item_id].text[:800]}
                    for item_id in evidence_ids[:8]
                ],
                "preferred_sources": [
                    {
                        "id": "unterm",
                        "authority": "official",
                        "url": "https://unterm.un.org/",
                        "scope": "United Nations system terminology; use only when the concept is in scope.",
                    },
                    {
                        "id": "iate",
                        "authority": "official",
                        "url": "https://iate.europa.eu/",
                        "scope": "European Union terminology; use only when the concept is in scope.",
                    },
                ],
                "candidate_contract": {
                    "required_fields": [
                        "term", "candidate_translation", "authority", "source_title", "source_url",
                        "source_excerpt", "evidence_segment_ids", "confidence",
                    ],
                    "rules": [
                        "Return only candidates supported by the cited source.",
                        "Do not infer a Chinese rendering from an English-only source.",
                        "Do not elevate a source outside its disciplinary scope.",
                    ],
                },
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return len(rows)


def terminology_impact(root: Path, term: str) -> list[Segment]:
    """Return the stable source Segments affected by a terminology correction."""
    needle = term.casefold().strip()
    if not needle:
        raise ValueError("term must be non-empty")
    return [
        item for item in read_jsonl(root / STATE / "segments.jsonl", Segment)
        if needle in item.text.casefold()
    ]


def _project_language(root: Path, field: str) -> str:
    return str(json.loads((root / "project.json").read_text(encoding="utf-8"))[field])


def propose_knowledge(
    root: Path, minimum_occurrences: int = 2
) -> tuple[list[GlossaryEntry], list[Entity]]:
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
    glossary = existing_glossary + [
        GlossaryEntry(
            term,
            "",
            [],
            "Candidate extracted from repeated source usage",
            ids[0],
            min(0.9, 0.5 + len(ids) * 0.1),
            ids,
            "proposed",
        )
        for term, ids in sorted(selected.items())
        if term.casefold() not in known_terms
    ]
    entities = existing_entities + [
        Entity(
            stable_id("ent", term),
            term,
            "unknown",
            "Candidate entity; classify during review",
            [],
            ids,
            min(0.9, 0.5 + len(ids) * 0.1),
            "proposed",
        )
        for term, ids in sorted(selected.items())
        if term.casefold() not in known_entities
    ]
    _write_glossary(root / STATE / "glossary.csv", glossary)
    write_jsonl(root / STATE / "entities.jsonl", entities)
    return glossary, entities


def _write_glossary(path: Path, entries: list[GlossaryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "term",
                "preferred_translation",
                "allowed_variants",
                "note",
                "source_segment_id",
                "confidence",
                "evidence_segment_ids",
                "status",
            ]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.term,
                    entry.preferred_translation,
                    "|".join(entry.allowed_variants),
                    entry.note,
                    entry.source_segment_id or "",
                    entry.confidence,
                    "|".join(entry.evidence_segment_ids),
                    entry.status,
                ]
            )


def _read_glossary(path: Path) -> list[GlossaryEntry]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            GlossaryEntry(
                row["term"],
                row["preferred_translation"],
                [item for item in row["allowed_variants"].split("|") if item],
                row["note"],
                row["source_segment_id"] or None,
                float(row["confidence"] or 1),
                [item for item in row.get("evidence_segment_ids", "").split("|") if item],
                row.get("status", "approved") or "approved",
            )
            for row in csv.DictReader(handle)
            if row["term"]
        ]
