#!/usr/bin/env python3
"""Read-only ContextWeaver project inspection for Codex workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def jsonl_unique_count(path: Path, field: str) -> int:
    if not path.exists():
        return 0
    return len({
        json.loads(line).get(field) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get(field) is not None
    })


def jsonl_status_count(path: Path, status: str) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("status", "open") == status
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    config = root / "project.json"
    if not config.exists():
        print(json.dumps({"is_project": False, "path": str(root), "next": "init"}, indent=2))
        return 1
    project = json.loads(config.read_text(encoding="utf-8"))
    manifest_path = root / "state" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    issues_path = root / "state" / "issues.jsonl"
    open_issues = 0
    if issues_path.exists():
        for line in issues_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("status", "open") == "open":
                open_issues += 1
    output_names = (
        "translated.md", "bilingual.md", "translated.epub", "bilingual.epub",
        "reference-zh-CN.md", "reference-zh-CN.epub",
    )
    outputs = [str(root / "output" / name) for name in output_names if (root / "output" / name).exists()]
    outputs.extend(
        str(path) for path in sorted((root / "output" / "sections").glob("*/*"))
        if path.suffix in {".md", ".epub"}
    )
    brief_path = root / "state" / "translation_brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8")) if brief_path.exists() else None
    result = {
        "is_project": True,
        "path": str(root),
        "name": project.get("name"),
        "schema_version": project.get("schema_version", 1),
        "languages": [project.get("source_language"), project.get("target_language")],
        "steps": manifest.get("steps", {}),
        "counts": {
            "sections": jsonl_count(root / "state" / "sections.jsonl"),
            "segments": jsonl_count(root / "state" / "segments.jsonl"),
            "units": jsonl_count(root / "state" / "units.jsonl"),
            "translation_records": jsonl_count(root / "state" / "translations.jsonl"),
            "translation_reviews": jsonl_count(root / "state" / "reviews.jsonl"),
            "scope_reviews": jsonl_count(root / "state" / "scope_reviews.jsonl"),
            "section_summary_records": jsonl_count(root / "state" / "section_summaries.jsonl"),
            "summarized_sections": jsonl_unique_count(
                root / "state" / "section_summaries.jsonl", "section_id"
            ),
            "ambiguities": jsonl_count(root / "state" / "ambiguities.jsonl"),
            "open_ambiguities": jsonl_status_count(
                root / "state" / "ambiguities.jsonl", "open"
            ),
            "open_issues": open_issues,
            "reference_sections": jsonl_count(root / "state" / "reference" / "sections.jsonl"),
            "reference_segments": jsonl_count(root / "state" / "reference" / "segments.jsonl"),
            "aligned_chapters": jsonl_count(root / "state" / "reference" / "alignments.jsonl"),
            "locale_adaptations": jsonl_count(root / "state" / "reference" / "segments.zh-CN.jsonl"),
        },
        "translation_strategy": None if brief is None else {
            "genre": brief.get("genre"),
            "domains": brief.get("domains", []),
            "concept_rule_count": len(brief.get("concept_rules", [])),
            "generated_by": brief.get("generated_by", {}),
            "human_review_required": brief.get("human_review_required", False),
        },
        "outputs": outputs,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
