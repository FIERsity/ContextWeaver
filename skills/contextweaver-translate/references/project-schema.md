# Project schema v2

- `project.json`: languages, project identity, schema version.
- `source/original.*`: immutable imported artifact.
- `source/document.md`: transparent normalized source.
- `state/manifest.json`: pipeline steps and counts.
- `state/sections.jsonl`: hierarchical headings.
- `state/segments.jsonl`: stable IDs, plain text, raw Markdown, block kind, source locator, format signature.
- `state/units.jsonl`: bounded translation batches.
- `state/glossary.csv`: editable terminology decisions and evidence.
- `state/entities.jsonl`: editable cross-section entities and evidence.
- `state/translations.jsonl`: append-only translations and revision links.
- `state/reviews.jsonl`: append-only Critic/Reviser decisions binding exact input and output TranslationRecord IDs, categories, rationale, confidence, and reviewer attribution.
- `state/scope_reviews.jsonl`: append-only Section/book review fingerprints, bounded evidence IDs, consistency decisions, and linked multi-Segment revisions.
- `state/section_summaries.jsonl`: append-only Section context with source/strategy digest, evidence, confidence, revision, and `supersedes`.
- `state/ambiguities.jsonl`: evidence-backed unresolved reference, term, entity, source, rhetoric, or other questions; human resolution is optional.
- `state/translation_brief.json`: automatic work profile, target style, principles, concept rules, evidence, confidence, and generator attribution. Human approval is optional.
- `state/issues.jsonl`: current validation findings.
- `state/export_metadata.json`: source authority, translator/Agent attribution, human-reference credit, and fidelity policy.
- `notes/translation_brief.md`: editable human-readable mirror of the automatic strategy.
- `notes/section_summaries.md`: readable mirror of the latest automatic Section summaries.
- `state/import_report.json`: source structure counts and known conversion losses.
- `state/reference/`: local human translation, chapter alignment, import report, and optional locale adaptations.
- `output/translated.md`: target-only export.
- `output/bilingual.md`: aligned source/target export.
- `output/translated.epub`: target-only reader-ready EPUB.
- `output/bilingual.epub`: aligned source/target EPUB.
- `output/reference-zh-CN.md`: unapproved Mainland Simplified reference draft when requested.
- `output/reference-zh-CN.epub`: EPUB form of the same unapproved reference draft.

Treat JSONL ordering as meaningful. Do not rewrite stable IDs, delete historical translation records, or introduce fields without a migration.
