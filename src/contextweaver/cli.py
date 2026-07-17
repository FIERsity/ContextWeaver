"""Command-line interface for independent, resumable pipeline steps."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .adapters import MockTranslationAdapter, OpenAITranslationAdapter
from .knowledge import propose_knowledge
from .pipeline import (
    export_project,
    import_document,
    init_project,
    migrate_project,
    project_status,
    replace_document,
    segment_document,
    translate_project,
    validate_project,
)

LOG = logging.getLogger("contextweaver")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="contextweaver", description="Context-aware long-form translation pipeline")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a translation project")
    init.add_argument("path", type=Path)
    init.add_argument("--name")
    init.add_argument("--source-language", default="en")
    init.add_argument("--target-language", default="zh-CN")
    imp = commands.add_parser("import", help="Import Markdown, TXT, DOCX, or EPUB")
    imp.add_argument("project", type=Path)
    imp.add_argument("source", type=Path)
    imp.add_argument("--replace", action="store_true", help="Replace source and generated pipeline state")
    seg = commands.add_parser("segment", help="Create stable segments and translation units")
    seg.add_argument("project", type=Path)
    seg.add_argument("--unit-size", type=int, default=3)
    trans = commands.add_parser("translate", help="Translate pending units")
    trans.add_argument("project", type=Path)
    trans.add_argument("--adapter", choices=["mock", "openai"], default="mock")
    trans.add_argument("--model", default="gpt-5.6-sol")
    trans.add_argument("--requests-per-minute", type=float, default=60)
    trans.add_argument("--segment", action="append", default=[], help="Retranslate a segment ID; repeatable")
    trans.add_argument("--section", action="append", default=[], help="Retranslate every segment in a section ID")
    trans.add_argument("--term", help="Retranslate segments whose source contains this term")
    trans.add_argument("--reason", default="manual-selection", help="Revision reason stored in each new record")
    val = commands.add_parser("validate", help="Validate one-to-one source/translation alignment")
    val.add_argument("project", type=Path)
    exp = commands.add_parser("export", help="Export translated and bilingual Markdown")
    exp.add_argument("project", type=Path)
    status = commands.add_parser("status", help="Show pipeline progress")
    status.add_argument("project", type=Path)
    extract = commands.add_parser("extract-knowledge", help="Create editable glossary/entity proposals with evidence")
    extract.add_argument("project", type=Path)
    extract.add_argument("--minimum-occurrences", type=int, default=2)
    migrate = commands.add_parser("migrate", help="Migrate persisted project data to the latest schema")
    migrate.add_argument("project", type=Path)
    return root


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "init":
            project = init_project(args.path, args.name or args.path.name, args.source_language, args.target_language)
            LOG.info("Created project %s at %s", project.id, args.path.resolve())
        elif args.command == "import":
            document = replace_document(args.project, args.source) if args.replace else import_document(args.project, args.source)
            LOG.info("Imported %s (%s)", document.title, document.sha256[:12])
        elif args.command == "segment":
            sections, segments, units = segment_document(args.project, args.unit_size)
            LOG.info("Created %d sections, %d segments, %d units", len(sections), len(segments), len(units))
        elif args.command == "translate":
            adapter = MockTranslationAdapter() if args.adapter == "mock" else OpenAITranslationAdapter(
                model=args.model, requests_per_minute=args.requests_per_minute
            )
            written, skipped = translate_project(
                args.project, adapter, set(args.segment) or None, set(args.section) or None,
                args.term, args.reason,
            )
            LOG.info("Translated %d segments; skipped %d completed segments", written, skipped)
        elif args.command == "validate":
            issues = validate_project(args.project)
            for issue in issues:
                LOG.error("%s: %s (%s)", issue.kind, issue.message, issue.segment_id)
            LOG.info("Validation completed with %d issue(s)", len(issues))
            return 1 if any(issue.severity == "error" for issue in issues) else 0
        elif args.command == "export":
            translated, bilingual = export_project(args.project)
            LOG.info("Wrote %s and %s", translated, bilingual)
        elif args.command == "status":
            print(json.dumps(project_status(args.project).to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "extract-knowledge":
            glossary, entities = propose_knowledge(args.project, args.minimum_occurrences)
            LOG.info("Proposed %d glossary entries and %d entities", len(glossary), len(entities))
        elif args.command == "migrate":
            LOG.info("Project schema is now version %d", migrate_project(args.project))
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        LOG.error("%s", exc)
        return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
