"""Automatic, evidence-backed book profiling and translation strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from .models import Project, Section, Segment, SourceDocument
from .pipeline import STATE
from .storage import read_json, read_jsonl, write_json


class BookAnalysisAdapter(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the editable strategy fields for one long-form work."""


class HeuristicBookAnalysisAdapter(BookAnalysisAdapter):
    """Deterministic offline profiler used for safe workflow tests."""

    name = "heuristic"
    model = "domain-signals-v1"

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = "\n".join(item["text"] for item in payload["samples"])
        lowered = text.casefold()
        domains = []
        signals = {
            "political economy": ("power", "wage", "worker", "capital", "prosperity"),
            "technology and society": ("technology", "machine", "innovation", "digital"),
            "history": ("century", "history", "medieval", "revolution"),
            "social science": ("society", "institution", "inequality", "political"),
        }
        scores = {
            domain: sum(lowered.count(word) for word in words) for domain, words in signals.items()
        }
        domains = [
            domain for domain, score in sorted(scores.items(), key=lambda item: -item[1]) if score
        ][:3]
        genre = (
            "long-form nonfiction" if payload["segment_count"] >= 20 else "short-form nonfiction"
        )
        rules = _concept_rules(payload["concept_evidence"])
        return {
            "genre": genre,
            "domains": domains or ["general nonfiction"],
            "source_style": "argument-led expository prose with narrative evidence",
            "target_style": "idiomatic Mainland Simplified Chinese with semantic fidelity",
            "audience": "educated general readers",
            "principles": [
                "Treat the source text as the sole semantic authority.",
                "Preserve facts, qualifications, argument relations, tone, and important rhetoric.",
                "Prefer native Chinese clause order and sentence rhythm over English-shaped syntax.",
                "Keep domain concepts distinct even when everyday Chinese offers a looser synonym.",
                "Record uncertainty instead of silently adding an explanation.",
            ],
            "concept_rules": rules,
            "confidence": 0.65 if rules else 0.5,
        }


class OpenAIBookAnalysisAdapter(BookAnalysisAdapter):
    """Optional online Agent profiler using a strict structured response."""

    name = "openai"

    def __init__(
        self, model: str = "gpt-5.6-sol", *, client: Any = None, api_key: str | None = None
    ) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install ContextWeaver with the 'openai' extra") from exc
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY is required for OpenAI analysis")
            client = OpenAI(api_key=key)
        self.client = client
        self.model = model

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": {
                "genre": {"type": "string"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "source_style": {"type": "string"},
                "target_style": {"type": "string"},
                "audience": {"type": "string"},
                "principles": {"type": "array", "items": {"type": "string"}},
                "concept_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_term": {"type": "string"},
                            "preferred_rendering": {"type": "string"},
                            "guidance": {"type": "string"},
                            "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "source_term",
                            "preferred_rendering",
                            "guidance",
                            "evidence_segment_ids",
                            "confidence",
                        ],
                        "additionalProperties": False,
                    },
                },
                "confidence": {"type": "number"},
            },
            "required": [
                "genre",
                "domains",
                "source_style",
                "target_style",
                "audience",
                "principles",
                "concept_rules",
                "confidence",
            ],
            "additionalProperties": False,
        }
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "Profile this complete work before translation. Infer genre, disciplinary register, authorial style, target-reader style, and high-impact polysemous concepts. "
                "Use evidence segment IDs. A concept rule guides context-sensitive sense selection, not blind one-to-one replacement. "
                "For zh-CN require source-faithful natural Chinese. Human approval is optional: produce a usable autonomous strategy and express uncertainty through confidence."
            ),
            input=json.dumps(payload, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "translation_strategy",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return dict(json.loads(response.output_text))


def analyze_project(
    root: Path, adapter: BookAnalysisAdapter, *, refresh: bool = False
) -> dict[str, Any]:
    path = root / STATE / "translation_brief.json"
    if path.exists() and not refresh:
        return read_json(path)
    project = Project(**read_json(root / "project.json"))
    source = SourceDocument(**read_json(root / STATE / "source_document.json"))
    sections = read_jsonl(root / STATE / "sections.jsonl", Section)
    segments = read_jsonl(root / STATE / "segments.jsonl", Segment)
    if not segments:
        raise RuntimeError("No segments. Run segment before analyze.")
    samples = _samples(sections, segments)
    result = adapter.analyze(
        {
            "project": project.to_dict(),
            "source": source.to_dict(),
            "section_count": len(sections),
            "segment_count": len(segments),
            "samples": samples,
            "concept_evidence": _concept_evidence(segments),
        }
    )
    brief = {
        "schema_version": 1,
        "project_id": project.id,
        "generated_by": {"adapter": adapter.name, "model": adapter.model},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "human_review_required": False,
        "sample_segment_ids": [item["segment_id"] for item in samples],
        **result,
    }
    write_json(path, brief)
    notes = root / "notes" / "translation_brief.md"
    notes.write_text(_markdown(brief), encoding="utf-8")
    return brief


def _samples(
    sections: list[Section], segments: list[Segment], limit: int = 48
) -> list[dict[str, str]]:
    by_section: dict[str, list[Segment]] = {}
    for segment in segments:
        by_section.setdefault(segment.section_id, []).append(segment)
    chosen: list[Segment] = []
    for section in sections:
        items = by_section.get(section.id, [])
        if items:
            chosen.extend([items[0], items[len(items) // 2], items[-1]])
    unique = {item.id: item for item in chosen}
    ordered = sorted(unique.values(), key=lambda item: item.ordinal)[:limit]
    return [{"segment_id": item.id, "text": item.text[:1600]} for item in ordered]


def _concept_rules(samples: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates = {
        "power": (
            "权力（支配或决策语境）；力量/能力（物理或技术语境）",
            "Distinguish institutional authority from physical or technical capacity.",
        ),
        "capital": (
            "资本",
            "Distinguish financial or productive capital from a capital city or uppercase letter.",
        ),
        "labor": (
            "劳动/劳动力",
            "Use labor for activity and labor force for the people supplying it.",
        ),
        "progress": (
            "进步",
            "Preserve its evaluative and contested role when it is a core argument term.",
        ),
        "productivity": (
            "生产率",
            "Prefer the economics term over the looser 生产效率 when measurable output is meant.",
        ),
        "agency": (
            "能动性/行动能力",
            "Do not confuse personal agency with an organization or intermediary.",
        ),
        "empowered": (
            "获得权力/自主权得到增强",
            "Use the institutional or social sense when participation and control are at stake.",
        ),
        "disempowered": (
            "权力受到削弱",
            "Do not weaken a political-economic loss of power into the vague 失去力量.",
        ),
    }
    evidence: dict[str, list[str]] = {term: [] for term in candidates}
    for sample in samples:
        words = Counter(re.findall(r"[A-Za-z]+", sample["text"].casefold()))
        for term in candidates:
            if words[term]:
                evidence[term].append(sample["segment_id"])
    return [
        {
            "source_term": term,
            "preferred_rendering": candidates[term][0],
            "guidance": candidates[term][1],
            "evidence_segment_ids": ids[:8],
            "confidence": round(min(0.9, 0.55 + len(ids) * 0.05), 2),
        }
        for term, ids in evidence.items()
        if ids
    ]


def _concept_evidence(segments: list[Segment]) -> list[dict[str, str]]:
    terms = (
        "power",
        "capital",
        "labor",
        "progress",
        "productivity",
        "agency",
        "empowered",
        "disempowered",
    )
    found: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    for segment in segments:
        lowered = segment.text.casefold()
        matched = [term for term in terms if re.search(rf"\b{re.escape(term)}\b", lowered)]
        if not matched:
            continue
        for term in matched:
            if counts[term] < 8:
                found.append({"segment_id": segment.id, "text": segment.text[:600]})
                counts[term] += 1
    return found


def _markdown(brief: dict[str, Any]) -> str:
    lines = [
        "# Translation brief",
        "",
        "> Generated automatically; human editing is optional.",
        "",
        f"- Genre: {brief['genre']}",
        f"- Domains: {', '.join(brief['domains'])}",
        f"- Source style: {brief['source_style']}",
        f"- Target style: {brief['target_style']}",
        f"- Audience: {brief['audience']}",
        f"- Confidence: {brief['confidence']}",
        "",
        "## Principles",
        "",
    ]
    lines.extend(f"- {item}" for item in brief["principles"])
    lines.extend(["", "## Concept rules", ""])
    for rule in brief["concept_rules"]:
        lines.extend(
            [
                f"### {rule['source_term']}",
                "",
                f"- Preferred: {rule['preferred_rendering']}",
                f"- Guidance: {rule['guidance']}",
                f"- Confidence: {rule['confidence']}",
                f"- Evidence: {', '.join(rule['evidence_segment_ids'])}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
