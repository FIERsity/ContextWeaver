"""Command-line interface for independent, resumable pipeline steps."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .adapters import (
    HeuristicReviewAdapter,
    MockTranslationAdapter,
    OpenAIReviewAdapter,
    OpenAITranslationAdapter,
)
from .audit import audit_project
from .coherence import review_book, review_sections
from .coherence_adapters import (
    HeuristicCoherenceReviewAdapter,
    OpenAICoherenceReviewAdapter,
)
from .knowledge import propose_knowledge
from .reference import import_reference, simplify_reference_outputs
from .review import review_project
from .strategy import HeuristicBookAnalysisAdapter, OpenAIBookAnalysisAdapter, analyze_project
from .summaries import summarize_project
from .summary_adapters import HeuristicSummaryAdapter, OpenAISummaryAdapter
from .pipeline import (
    export_selected,
    export_agent_batch,
    import_document,
    import_translation_draft,
    import_section_title_draft,
    init_project,
    migrate_project,
    project_status,
    replace_document,
    segment_document,
    translate_project,
    translate_section_titles,
    validate_project,
)

LOG = logging.getLogger("contextweaver")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="contextweaver", description="Context-aware long-form translation pipeline"
    )
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
    imp.add_argument(
        "--replace", action="store_true", help="Replace source and generated pipeline state"
    )
    seg = commands.add_parser("segment", help="Create stable segments and translation units")
    seg.add_argument("project", type=Path)
    seg.add_argument("--unit-size", type=int, default=3)
    trans = commands.add_parser("translate", help="Translate pending units")
    trans.add_argument("project", type=Path)
    trans.add_argument("--adapter", choices=["mock", "openai"], default="mock")
    trans.add_argument("--model", default="gpt-5.6-sol")
    trans.add_argument("--requests-per-minute", type=float, default=60)
    trans.add_argument(
        "--segment", action="append", default=[], help="Retranslate a segment ID; repeatable"
    )
    trans.add_argument(
        "--section", action="append", default=[], help="Retranslate every segment in a section ID"
    )
    trans.add_argument("--term", help="Retranslate segments whose source contains this term")
    trans.add_argument(
        "--reason", default="manual-selection", help="Revision reason stored in each new record"
    )
    trans.add_argument(
        "--max-units",
        type=int,
        help="Process at most this many pending TranslationUnits, then exit resumably",
    )
    val = commands.add_parser("validate", help="Validate one-to-one source/translation alignment")
    val.add_argument("project", type=Path)
    val.add_argument(
        "--section", action="append", default=[], help="Validate only selected section IDs"
    )
    val.add_argument(
        "--segment", action="append", default=[], help="Validate only selected segment IDs"
    )
    exp = commands.add_parser("export", help="Export selected Markdown and/or EPUB artifacts")
    exp.add_argument("project", type=Path)
    exp.add_argument("--format", choices=["markdown", "epub", "all"], default="markdown")
    exp.add_argument("--content", choices=["translated", "bilingual", "all"], default="all")
    exp.add_argument("--translator", help="Translator/agent credit embedded in output metadata")
    exp.add_argument("--reference-credit", help="Human translation consulted as reference")
    exp.add_argument(
        "--section", action="append", default=[], help="Export only selected section IDs"
    )
    exp.add_argument(
        "--segment", action="append", default=[], help="Export only selected segment IDs"
    )
    status = commands.add_parser("status", help="Show pipeline progress")
    status.add_argument("project", type=Path)
    extract = commands.add_parser(
        "extract-knowledge", help="Create editable glossary/entity proposals with evidence"
    )
    extract.add_argument("project", type=Path)
    extract.add_argument("--minimum-occurrences", type=int, default=2)
    migrate = commands.add_parser(
        "migrate", help="Migrate persisted project data to the latest schema"
    )
    migrate.add_argument("project", type=Path)
    reference = commands.add_parser(
        "reference-import", help="Import and chapter-align a human translation"
    )
    reference.add_argument("project", type=Path)
    reference.add_argument("source", type=Path)
    reference.add_argument("--language", required=True)
    reference.add_argument("--credit", default="", help="Translator and edition used as reference")
    simplify = commands.add_parser(
        "reference-simplify", help="Create a review draft in Mainland Simplified Chinese"
    )
    simplify.add_argument("project", type=Path)
    simplify.add_argument("--format", choices=["markdown", "epub", "all"], default="markdown")
    draft = commands.add_parser(
        "translation-import", help="Import Agent-produced segment translations from JSONL"
    )
    draft.add_argument("project", type=Path)
    draft.add_argument("draft", type=Path)
    draft.add_argument("--adapter", default="codex-agent")
    draft.add_argument("--model", required=True)
    draft.add_argument("--reason", required=True)
    batch = commands.add_parser(
        "agent-batch", help="Export pending TranslationUnits with bounded Agent context"
    )
    batch.add_argument("project", type=Path)
    batch.add_argument("output", type=Path)
    batch.add_argument("--section", action="append", default=[])
    batch.add_argument(
        "--max-units",
        type=int,
        help="Explicit unit limit; omit to use the adaptive chapter-bounded strategy",
    )
    batch.add_argument(
        "--target-source-chars",
        type=int,
        default=40_000,
        help="Adaptive source-character budget (default: 40000)",
    )
    batch.add_argument("--force", action="store_true", help="Replace an existing work-package file")
    titles = commands.add_parser(
        "translate-titles", help="Translate missing Section titles without changing Section IDs"
    )
    titles.add_argument("project", type=Path)
    titles.add_argument("--adapter", choices=["mock", "openai"], default="mock")
    titles.add_argument("--model", default="gpt-5.6-sol")
    titles.add_argument("--requests-per-minute", type=float, default=60)
    titles.add_argument("--section", action="append", default=[])
    titles.add_argument("--refresh", action="store_true")
    titles.add_argument("--reason", default="section-title-translation")
    title_draft = commands.add_parser(
        "section-title-import", help="Import Agent-produced Section title translations"
    )
    title_draft.add_argument("project", type=Path)
    title_draft.add_argument("draft", type=Path)
    title_draft.add_argument("--adapter", default="codex-agent")
    title_draft.add_argument("--model", required=True)
    title_draft.add_argument("--reason", required=True)
    analyze = commands.add_parser(
        "analyze", help="Automatically profile the work and create a translation strategy"
    )
    analyze.add_argument("project", type=Path)
    analyze.add_argument("--adapter", choices=["heuristic", "openai"], default="heuristic")
    analyze.add_argument("--model", default="gpt-5.6-sol")
    analyze.add_argument(
        "--refresh",
        action="store_true",
        help="Replace the generated strategy; human edits may be lost",
    )
    review = commands.add_parser(
        "review", help="Critique active translations and append needed revisions"
    )
    review.add_argument("project", type=Path)
    review.add_argument("--adapter", choices=["heuristic", "openai"], default="heuristic")
    review.add_argument("--model", default="gpt-5.6-sol")
    review.add_argument("--requests-per-minute", type=float, default=30)
    review.add_argument("--segment", action="append", default=[])
    review.add_argument("--section", action="append", default=[])
    coherence = commands.add_parser(
        "coherence-review", help="Review chapter-level and whole-book consistency"
    )
    coherence.add_argument("project", type=Path)
    coherence.add_argument("--scope", choices=["section", "book", "all"], default="all")
    coherence.add_argument("--adapter", choices=["heuristic", "openai"], default="heuristic")
    coherence.add_argument("--model", default="gpt-5.6-sol")
    coherence.add_argument("--requests-per-minute", type=float, default=30)
    coherence.add_argument("--section", action="append", default=[])
    summarize = commands.add_parser(
        "summarize", help="Generate resumable Section summaries and ambiguity records"
    )
    summarize.add_argument("project", type=Path)
    summarize.add_argument("--adapter", choices=["heuristic", "openai"], default="heuristic")
    summarize.add_argument("--model", default="gpt-5.6-sol")
    summarize.add_argument("--requests-per-minute", type=float, default=30)
    summarize.add_argument("--section", action="append", default=[])
    summarize.add_argument("--refresh", action="store_true")
    audit = commands.add_parser("audit", help="Write an evidence-backed v1 readiness report")
    audit.add_argument("project", type=Path)
    audit.add_argument(
        "--allow-mock",
        action="store_true",
        help="Allow mock translations for workflow tests; never use for release readiness",
    )
    auto = commands.add_parser(
        "auto", help="Run the resumable Agent-first path from analysis through export"
    )
    auto.add_argument("project", type=Path)
    auto.add_argument("--adapter", choices=["mock", "openai"], default="mock")
    auto.add_argument("--model", default="gpt-5.6-sol")
    auto.add_argument("--requests-per-minute", type=float, default=30)
    auto.add_argument("--format", choices=["markdown", "epub", "all"], default="all")
    auto.add_argument("--content", choices=["translated", "bilingual", "all"], default="all")
    auto.add_argument("--refresh-analysis", action="store_true")
    auto.add_argument("--translator")
    auto.add_argument("--reference-credit")
    auto.add_argument(
        "--skip-review", action="store_true", help="Skip the default Agent critic/reviser pass"
    )
    auto.add_argument(
        "--max-review-rounds",
        type=int,
        default=3,
        help="Maximum Segment/Section/book convergence rounds",
    )
    auto.add_argument(
        "--max-units",
        type=int,
        help="Translate at most this many pending units and stop before review/export if incomplete",
    )
    return root


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    try:
        if args.command == "init":
            project = init_project(
                args.path, args.name or args.path.name, args.source_language, args.target_language
            )
            LOG.info("Created project %s at %s", project.id, args.path.resolve())
        elif args.command == "import":
            document = (
                replace_document(args.project, args.source)
                if args.replace
                else import_document(args.project, args.source)
            )
            LOG.info("Imported %s (%s)", document.title, document.sha256[:12])
        elif args.command == "segment":
            sections, segments, units = segment_document(args.project, args.unit_size)
            LOG.info(
                "Created %d sections, %d segments, %d units",
                len(sections),
                len(segments),
                len(units),
            )
        elif args.command == "translate":
            adapter = (
                MockTranslationAdapter()
                if args.adapter == "mock"
                else OpenAITranslationAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            written, skipped = translate_project(
                args.project,
                adapter,
                set(args.segment) or None,
                set(args.section) or None,
                args.term,
                args.reason,
                args.max_units,
            )
            LOG.info("Translated %d segments; skipped %d completed segments", written, skipped)
        elif args.command == "validate":
            issues = validate_project(
                args.project, set(args.section) or None, set(args.segment) or None
            )
            for issue in issues:
                LOG.error("%s: %s (%s)", issue.kind, issue.message, issue.segment_id)
            LOG.info("Validation completed with %d issue(s)", len(issues))
            return 1 if any(issue.severity == "error" for issue in issues) else 0
        elif args.command == "export":
            formats = {"markdown", "epub"} if args.format == "all" else {args.format}
            contents = {"translated", "bilingual"} if args.content == "all" else {args.content}
            paths = export_selected(
                args.project,
                formats,
                contents,
                args.translator,
                args.reference_credit,
                set(args.section) or None,
                set(args.segment) or None,
            )
            LOG.info("Wrote %d artifact(s): %s", len(paths), ", ".join(str(path) for path in paths))
        elif args.command == "status":
            print(json.dumps(project_status(args.project).to_dict(), ensure_ascii=False, indent=2))
        elif args.command == "extract-knowledge":
            glossary, entities = propose_knowledge(args.project, args.minimum_occurrences)
            LOG.info("Proposed %d glossary entries and %d entities", len(glossary), len(entities))
        elif args.command == "migrate":
            LOG.info("Project schema is now version %d", migrate_project(args.project))
        elif args.command == "reference-import":
            sections, segments, alignments = import_reference(
                args.project, args.source, args.language, args.credit
            )
            LOG.info(
                "Imported reference with %d sections and %d segments; aligned %d chapters",
                sections,
                segments,
                alignments,
            )
        elif args.command == "reference-simplify":
            formats = {"markdown", "epub"} if args.format == "all" else {args.format}
            count, paths = simplify_reference_outputs(args.project, formats)
            LOG.info(
                "Wrote %d draft locale adaptations to %s",
                count,
                ", ".join(str(path) for path in paths),
            )
        elif args.command == "translation-import":
            count = import_translation_draft(
                args.project, args.draft, args.adapter, args.model, args.reason
            )
            LOG.info("Imported %d translation revision(s)", count)
        elif args.command == "agent-batch":
            units, segments = export_agent_batch(
                args.project,
                args.output,
                set(args.section) or None,
                args.max_units,
                args.force,
                args.target_source_chars,
            )
            LOG.info(
                "Wrote %d pending unit(s) containing %d segment(s) to %s",
                units,
                segments,
                args.output,
            )
        elif args.command == "translate-titles":
            adapter = (
                MockTranslationAdapter()
                if args.adapter == "mock"
                else OpenAITranslationAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            written, skipped = translate_section_titles(
                args.project,
                adapter,
                set(args.section) or None,
                args.reason,
                args.refresh,
            )
            LOG.info("Translated %d Section title(s); skipped %d", written, skipped)
        elif args.command == "section-title-import":
            count = import_section_title_draft(
                args.project, args.draft, args.adapter, args.model, args.reason
            )
            LOG.info("Imported %d Section title revision(s)", count)
        elif args.command == "analyze":
            analyzer = (
                HeuristicBookAnalysisAdapter()
                if args.adapter == "heuristic"
                else OpenAIBookAnalysisAdapter(model=args.model)
            )
            brief = analyze_project(args.project, analyzer, refresh=args.refresh)
            LOG.info(
                "Generated %s strategy with %d concept rule(s)",
                brief["genre"],
                len(brief["concept_rules"]),
            )
        elif args.command == "review":
            reviewer = (
                HeuristicReviewAdapter()
                if args.adapter == "heuristic"
                else OpenAIReviewAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            reviewed, revised, skipped = review_project(
                args.project, reviewer, set(args.segment) or None, set(args.section) or None
            )
            LOG.info(
                "Reviewed %d translations; revised %d; skipped %d reviewed versions",
                reviewed,
                revised,
                skipped,
            )
        elif args.command == "coherence-review":
            reviewer = (
                HeuristicCoherenceReviewAdapter()
                if args.adapter == "heuristic"
                else OpenAICoherenceReviewAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            if args.scope in {"section", "all"}:
                reviewed, revised, skipped = review_sections(
                    args.project, reviewer, set(args.section) or None
                )
                LOG.info(
                    "Section review checked %d scope(s); revised %d translation(s); skipped %d",
                    reviewed,
                    revised,
                    skipped,
                )
            if args.scope in {"book", "all"}:
                reviewed, revised, skipped = review_book(args.project, reviewer)
                LOG.info(
                    "Book review checked %d scope(s); revised %d translation(s); skipped %d",
                    reviewed,
                    revised,
                    skipped,
                )
        elif args.command == "summarize":
            summary_adapter = (
                HeuristicSummaryAdapter()
                if args.adapter == "heuristic"
                else OpenAISummaryAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            generated, ambiguities, skipped = summarize_project(
                args.project,
                summary_adapter,
                set(args.section) or None,
                refresh=args.refresh,
            )
            LOG.info(
                "Generated %d Section summaries and %d ambiguity record(s); skipped %d",
                generated,
                ambiguities,
                skipped,
            )
        elif args.command == "audit":
            report = audit_project(args.project, allow_mock=args.allow_mock)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        elif args.command == "auto":
            if args.max_review_rounds < 1:
                raise ValueError("max-review-rounds must be at least 1")
            units_path = args.project / "state" / "units.jsonl"
            if not units_path.exists() or not units_path.read_text(encoding="utf-8").strip():
                sections, segments, units = segment_document(args.project)
                LOG.info(
                    "Segmented %d sections into %d segments and %d units",
                    len(sections),
                    len(segments),
                    len(units),
                )
            analyzer = (
                HeuristicBookAnalysisAdapter()
                if args.adapter == "mock"
                else OpenAIBookAnalysisAdapter(model=args.model)
            )
            brief = analyze_project(args.project, analyzer, refresh=args.refresh_analysis)
            LOG.info("Analysis ready: %s; human review is optional", brief["genre"])
            summary_adapter = (
                HeuristicSummaryAdapter()
                if args.adapter == "mock"
                else OpenAISummaryAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            generated, ambiguity_count, summary_skipped = summarize_project(
                args.project, summary_adapter
            )
            LOG.info(
                "Section context ready: %d generated, %d ambiguities, %d skipped",
                generated,
                ambiguity_count,
                summary_skipped,
            )
            glossary, entities = propose_knowledge(args.project)
            LOG.info("Knowledge ready: %d glossary rows, %d entities", len(glossary), len(entities))
            adapter = (
                MockTranslationAdapter()
                if args.adapter == "mock"
                else OpenAITranslationAdapter(
                    model=args.model, requests_per_minute=args.requests_per_minute
                )
            )
            title_written, title_skipped = translate_section_titles(
                args.project, adapter, reason="agent-first-auto"
            )
            LOG.info(
                "Translated %d Section title(s); skipped %d completed title(s)",
                title_written,
                title_skipped,
            )
            written, skipped = translate_project(
                args.project, adapter, reason="agent-first-auto", max_units=args.max_units
            )
            LOG.info("Translated %d segments; skipped %d completed segments", written, skipped)
            status = project_status(args.project)
            if status.translation_count < status.segment_count:
                LOG.info(
                    "Batch complete: %d/%d Segments translated; rerun auto to resume",
                    status.translation_count,
                    status.segment_count,
                )
                return 0
            if not args.skip_review:
                reviewer = (
                    HeuristicReviewAdapter()
                    if args.adapter == "mock"
                    else OpenAIReviewAdapter(
                        model=args.model, requests_per_minute=args.requests_per_minute
                    )
                )
                coherence_reviewer = (
                    HeuristicCoherenceReviewAdapter()
                    if args.adapter == "mock"
                    else OpenAICoherenceReviewAdapter(
                        model=args.model, requests_per_minute=args.requests_per_minute
                    )
                )
                converged = False
                for round_number in range(1, args.max_review_rounds + 1):
                    reviewed, revised, review_skipped = review_project(args.project, reviewer)
                    section_reviewed, section_revised, section_skipped = review_sections(
                        args.project, coherence_reviewer
                    )
                    book_reviewed, book_revised, book_skipped = review_book(
                        args.project, coherence_reviewer
                    )
                    round_revisions = revised + section_revised + book_revised
                    LOG.info(
                        "Review round %d checked %d Segment and %d scope version(s); "
                        "revised %d; skipped %d",
                        round_number,
                        reviewed,
                        section_reviewed + book_reviewed,
                        round_revisions,
                        review_skipped + section_skipped + book_skipped,
                    )
                    if round_revisions == 0:
                        converged = True
                        break
                if not converged:
                    raise RuntimeError(
                        f"Agent review did not converge after {args.max_review_rounds} round(s)"
                    )
            issues = validate_project(args.project)
            errors = [issue for issue in issues if issue.severity == "error"]
            if errors:
                LOG.error(
                    "Auto export blocked by %d validation error(s); state is resumable", len(errors)
                )
                return 1
            formats = {"markdown", "epub"} if args.format == "all" else {args.format}
            contents = {"translated", "bilingual"} if args.content == "all" else {args.content}
            paths = export_selected(
                args.project, formats, contents, args.translator, args.reference_credit
            )
            LOG.info(
                "Auto workflow wrote %d artifact(s): %s",
                len(paths),
                ", ".join(str(path) for path in paths),
            )
            audit = audit_project(args.project, allow_mock=args.adapter == "mock")
            LOG.info(
                "v1 audit: ready=%s passed=%d failed=%d",
                audit["ready"],
                audit["passed"],
                audit["failed"],
            )
            if (
                args.format == "all"
                and args.content == "all"
                and not args.skip_review
                and not audit["ready"]
            ):
                return 1
        return 0
    except (
        FileNotFoundError,
        FileExistsError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        LOG.error("%s", exc)
        return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
