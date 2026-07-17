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
- `state/issues.jsonl`: current validation findings.
- `output/translated.md`: target-only export.
- `output/bilingual.md`: aligned source/target export.

Treat JSONL ordering as meaningful. Do not rewrite stable IDs, delete historical translation records, or introduce fields without a migration.

