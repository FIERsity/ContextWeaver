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
    outputs = [str(path) for path in (root / "output" / "translated.md", root / "output" / "bilingual.md") if path.exists()]
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
            "open_issues": open_issues,
        },
        "outputs": outputs,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

