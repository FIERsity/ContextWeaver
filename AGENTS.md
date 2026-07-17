# Agent instructions

Read `README.md`, `docs/architecture.md`, `pyproject.toml`, schema migrations, and the relevant tests before changing code.

- Preserve stable Segment IDs. Any intentional ID algorithm change requires a documented migration and tests.
- Do not change persisted data formats without a schema-versioned migration path.
- Add or update tests for every behavior change.
- Never silently ignore import, translation, persistence, or validation errors.
- Keep provider/model adapters decoupled from domain models and pipeline logic.
- Never overwrite reviewed glossary/entity rows or historical TranslationRecords.
- Preserve `raw`, `kind`, `format_signature`, and `source_locator` when changing importers.
- Prefer small, verifiable changes over broad speculative abstractions.
- Keep operations resumable and safe by default; destructive behavior needs an explicit flag.
- Update related documentation and examples when behavior or CLI usage changes.
- Keep `skills/contextweaver-translate` synchronized with CLI, schema, and review-policy changes; validate it after edits.
- Do not copy code or structure from external projects without checking its license and documenting the influence.

Run `pytest` and `ruff check .` before submitting changes.
