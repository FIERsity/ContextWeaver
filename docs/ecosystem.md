# ContextWeaver and PaperWeaver

ContextWeaver and [PaperWeaver](https://github.com/FIERsity/PaperWeaver) are separate sibling repositories. A local parent directory may contain both, but each has its own Git history, remote, CI, releases, dependencies, and project state.

## Scope boundary

- **ContextWeaver** translates long-form, context-dependent documents such as books, reports, EPUBs, DOCX files, and scholarly articles. Its core concerns are stable Segment identity, resumable translation, terminology/entity evidence, revision history, validation, and bilingual export.
- **PaperWeaver** is specialized for academic papers and research-reader artifacts. Its core concerns are paper structure, source-grounded reading guides, article explanation, and later publication-oriented translation/layout.

The projects may share design principles and interoperable file contracts. They must not copy implementation between repositories or use Git submodules as a shortcut. If a component becomes demonstrably useful and stable in both projects, extract it into an independently versioned, licensed package with its own tests and provenance.

## Collaboration rule

Cross-repository work starts with a written contract: input/output schema, ownership, version compatibility, error behavior, and licensing. Until such a contract exists, a feature belongs to exactly one repository.
