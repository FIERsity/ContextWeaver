# ContextWeaver v1.0 acceptance target

ContextWeaver reaches v1.0 when it can autonomously turn a supported long-form source into a traceable, validated book artifact. Human review must remain available but must not be a pipeline dependency.

## Required capabilities

1. Import EPUB, DOCX, Markdown, and TXT while retaining the original, normalized source, structural locators, and an explicit loss report.
2. Generate stable Section, Segment, and TranslationUnit IDs that survive normal resume operations.
3. Automatically create an evidence-backed work profile, target style, and context-sensitive concept strategy before translation.
4. Translate through a provider-neutral Adapter with bounded context, rate limiting, retry, and unit-level durable progress.
5. Preserve append-only TranslationRecord revisions and support selective Segment, Section, and term retranslation.
6. Run three review levels: source-aligned Segment criticism, bounded Section coherence review, and bounded whole-book concept/style review.
7. Record every automatic review decision, input/output version, evidence scope, confidence, rationale, and model attribution.
8. Validate complete alignment, formatting, numeric anchors, acronyms, approved terminology, repeated sources, and export integrity without silently waiving errors.
9. Export translated and bilingual Markdown and EPUB with localized, revision-tracked Section titles plus source, Agent/model, and optional human-reference provenance.
10. Resume every expensive stage without repeating completed work or overwriting human or Agent edits.

## Release evidence

- All unit, integration, CLI, retry, resume, revision, review, validation, and EPUB-readback tests pass on Python 3.11 and newer.
- The Codex Skill validates and can operate the complete autonomous route from project inspection through export.
- A real long-form EPUB pilot reaches 100% Segment translation, zero blocking deterministic validation errors, completed Segment/Section/book review fingerprints, and readable translated and bilingual EPUB output.
- The real pilot can be interrupted and resumed without duplicate active translations or duplicate scope reviews.
- README, architecture, CLI help, package version, build artifacts, GitHub default branch, CI, and release notes describe the same behavior.
- Copyrighted source, reference, and generated book contents remain excluded from Git unless redistribution rights are confirmed.

## Explicit non-goals for v1.0

- GUI and hosted API.
- A mandatory human approval queue.
- Support for every publisher-specific EPUB layout.
- Perfect automated literary judgment.
- A heavyweight multi-Agent framework or opaque database.

After these gates pass, new providers, GUI work, richer format fidelity, and domain-specific evaluators belong to later releases rather than delaying v1.0.

Run `contextweaver audit PROJECT` to write the machine-readable gate at `state/v1_audit.json` and its readable evidence report at `notes/v1_audit.md`. A release candidate is ready only when this command reports `ready=true` without `--allow-mock`.
