# Architecture and invariants

ContextWeaver separates durable domain state from orchestration and provider calls.

1. Import retains the original artifact, normalizes it to Markdown, and records its SHA-256 digest.
2. Segmentation parses source-preserving Markdown blocks, then deterministically derives section, segment, and unit IDs.
3. Context assembly selects only the unit's source segments, immediate neighbors, optional section summary, glossary, and entity records.
4. An adapter returns exactly one string per requested segment. Cardinality and empty output are treated as hard errors.
5. Translation records are appended and completed Segment IDs are skipped. Selected segments append linked revisions.
6. Section title translations use a separate append-only revision chain, preserving stable Section and Segment IDs.
7. Validation selects the newest revision, requires complete alignment, and checks structure, terminology, suspicious length, and repeated-source consistency.

Before step 3, the Agent-first path samples every section and writes an automatic work profile. Human review is never a prerequisite for continuing.

## Agent-first translation strategy

`analyze` samples the beginning, middle, and end of each Section with a bounded total, then writes `state/translation_brief.json` plus the editable `notes/translation_brief.md`. The brief records genre, disciplinary domains, source style, target style, audience, behavioral principles, high-impact concept rules, evidence Segment IDs, confidence, and truthful generator attribution. It is auxiliary versioned state, so adding it does not alter schema-v2 domain records or stable IDs.

Every ContextPacket carries the current brief. Concept rules are context-sensitive sense guidance rather than global string replacements: for example, *power* may indicate social authority, physical force, or computational capacity. Existing briefs are reused on resume so manual edits are not overwritten; regeneration requires `--refresh` or `--refresh-analysis`.

`summarize` builds bounded source-only dossiers for each Section before translation. `section_summaries.jsonl` stores append-only summaries, key points, evidence Segment IDs, confidence, adapter/model, source-plus-strategy digest, revision, and `supersedes`. The latest summary enters every ContextPacket and later coherence-review dossier. A stable digest skips unchanged Sections; a changed translation strategy makes affected summaries eligible for regeneration. `notes/section_summaries.md` is the readable mirror.

Summarizers may emit conservative ambiguity records for unresolved references, terms, entities, source defects, or rhetoric. `ambiguities.jsonl` requires evidence Segment IDs and confidence. Open ambiguities inform coherence review but do not block autonomous translation or require human approval. Duplicate ambiguity identities are not appended on resume.

`auto` is the non-interactive main path. It segments when needed, creates or resumes analysis and summaries, extracts knowledge, translates pending Segments, and runs Segment, Section, and book review as a convergence loop. A round with revisions invalidates affected higher-level fingerprints, so another round is required; the run succeeds only after a full round makes no revision, or fails at the configured maximum. It then validates, exports only when blocking errors are absent, and writes the v1 readiness audit. Low-confidence strategy decisions do not require approval. Human review remains an optional correction and revision interface.

`--max-units` gives long runs an explicit cost and time boundary. Each successfully returned TranslationUnit is appended before the counter advances. When the limit is reached with untranslated Segments remaining, `auto` reports the durable coverage and exits before any incomplete Section/book review or export. A later invocation resumes from active TranslationRecords.

## Agent Critic and Reviser

`review` evaluates the newest TranslationRecord for each selected Segment against its source, adjacent context, current translation strategy, terminology, entities, and optional human-reference evidence. Review categories cover semantic fidelity, concept role, terminology, natural Chinese, rhetoric, and format. Provider-neutral ReviewAdapters return either `pass` or a complete replacement translation.

`state/reviews.jsonl` is append-only. Each TranslationReview stores the exact input TranslationRecord ID, accepted or revised output ID, adapter/model, verdict, categories, rationale, and confidence. A changed result is appended to `translations.jsonl` with prompt version `review-v1-agent-critic-reviser` and a `supersedes` link. Empty or unchanged revisions are hard errors. Both input and output IDs are marked reviewed, so reruns skip the same version while a later selective translation naturally becomes eligible for a new review.

Chapter and book coherence use `scope_reviews.jsonl`. Each ScopeReview fingerprints the ordered active TranslationRecord IDs before and after review, records the bounded evidence Segment IDs, and links any revised TranslationRecord IDs. A Section dossier contains all Segments when small; otherwise it combines evenly stratified passages with high-risk concept hits under a character budget. A book dossier combines first/middle/last passages from every Section with a bounded concept concordance. Reviewers may revise only evidence Segments, preventing unsupported edits to omitted text. Any later translation change alters the scope fingerprint and makes that scope eligible for review again.

## Evidence-backed completion

`audit` converts the v1 acceptance target into durable evidence at `state/v1_audit.json` with a readable mirror at `notes/v1_audit.md`. It checks retained inputs, import reporting, stable structural coverage, strategy and summaries, ambiguity plus terminology/entity evidence, complete non-mock active translations, revision chains, current Segment/Section/book review coverage, deterministic validation, translated and bilingual Markdown/EPUB artifacts, EPUB readback, and provenance. Partial projects fail with counts rather than being mistaken for complete. `--allow-mock` is restricted to workflow verification and is not release evidence.

## Stable identity

IDs use truncated SHA-256 values over namespaced inputs. Segment identity includes the imported document digest, section identity, source ordinal, and normalized text. The same imported bytes and segmentation algorithm therefore reproduce the same IDs. A changed source is a new document; it must not silently inherit translations from an older source.

Section headings are structural source data rather than ordinary Segments. `section_titles.jsonl` binds each Section ID and source-title digest to an append-only target-title revision. This avoids changing existing IDs while allowing Agent translation, human correction, resume, translated EPUB navigation, and bilingual source/target headings. Active title IDs enter coherence-review fingerprints, so a corrected chapter title makes affected reviews stale.

## Persistence

`project.json` and `manifest.json` describe the project and progress. Structural collections use JSONL, glossary data uses CSV, and exported documents use Markdown. Generated structural collections are written through a temporary file and atomically replaced. Translation records are append-only in the normal flow. Readers reject unknown fields so schema drift fails visibly rather than corrupting state.

SQLite is intentionally absent: phase-one state is small enough for transparent files, Git diffs are useful during review, and no transactional cross-process scheduling is needed yet. A future index or queue may use SQLite as a derived cache while retaining exportable canonical records.

## Safe evolution

`schema_version` is currently `2`. The `migrate` command upgrades v1 records with default structural and revision metadata without changing IDs. Further stored-format or ID changes require another migration and compatibility fixtures. Model-specific prompts, credentials, retry policies, and rate limits belong in adapter modules, not domain records.

## Import and structure preservation

Markdown-it token ranges retain each top-level block's raw Markdown, plain text, type, source line locator, and format signature. TXT headings are normalized to Markdown. DOCX headings, emphasis, simple lists, and tables are converted with `python-docx`; EPUB spine documents are converted with EbookLib and Beautiful Soup. The original file remains available to audit lossy conversion.

## Evidence-backed knowledge

`extract-knowledge` conservatively proposes repeated proper-name candidates. Glossary and entity records include confidence, review status, and evidence Segment IDs. Only approved records enter context packets, but proposed records never block the autonomous route. Extraction merges new candidates rather than overwriting later Agent or human decisions.

## Human translation references

Reference editions live under `state/reference` and never replace the source document or TranslationRecords. Explicit prologue/chapter keys align editions even when their EPUB spine and subsection layouts differ. A translation unit receives three approximately positioned reference segments from the full aligned chapter, keeping context bounded. For a zh-TW reference and zh-CN target, `reference-simplify` stores an OpenCC `tw2sp` draft beside the untouched human text; later model translation sees the Simplified draft as evidence and is instructed not to assume exact paragraph alignment or copy regional wording blindly.

The source-language Segment is the sole semantic authority. Prompt version `translate-v3-source-faithful-natural-zh` requires conflicts, additions, omissions, and changes in claim strength to be resolved against the source rather than the reference. For zh-CN, fidelity is semantic rather than syntactic: adapters may reorder clauses, split or merge sentences, restore natural Chinese subjects and transitions, and reshape punctuation, provided facts, qualifications, argument relations, tone, and important rhetoric remain intact. Reference credits remain separate from translator attribution.

Agent-native offline work uses `agent-batch` to export pending TranslationUnits as bounded, self-contained JSONL work items, followed by `translation-import` with strict two-field response JSONL. Package planning begins with the active model's context limit. The operational default assumes 400,000 tokens and starts with 25% source, 35% target, 25% shared context/instructions, and 15% safety. The 15% reserve is hard; the other shares are flexible. Selection estimates serialized input at four characters per token and Chinese output at 0.6 tokens per English source character, then fills at most the remaining 85%. A 400,000-character raw-source guardrail and 500 TranslationUnits remain secondary limits. This avoids both context overflow from repeated ContextPackets and tiny tail batches caused by an unnecessarily rigid input partition. Selection prefers a complete Section and never crosses the next Section boundary, but an oversized Section is split at a TranslationUnit boundary. `--context-window-tokens` supplies a model-specific limit, while explicit character or unit options override the derived policy. `state/batch_strategy.json` records every assumption and actual package metric.

`agent-campaign` adds a higher scheduling tier. Its compact `state/agent_campaign.json` can target every pending Segment in a book without serializing repeated ContextPackets. It partitions that durable scope into Section-bounded checkpoints using the same character and unit budgets, and refreshes each checkpoint as pending, in progress, or completed from active TranslationRecords. Replacing a Campaign scope requires explicit `--refresh`. Campaign size controls autonomous throughput; checkpoint size controls recovery and review risk; TranslationUnit size controls model context. These three limits are intentionally independent.

Deterministic fidelity checks currently compare numeric anchors (including currency and percentages), acronyms, Markdown structure, approved terminology, suspicious length, and repeated-source consistency. Semantic entailment and natural-language concept roles are handled by the optional online Critic/Reviser; the offline reviewer supplies deterministic workflow checks only.

Numeric comparison canonicalizes information rather than requiring identical character forms. Explicit English dates and Chinese numeric or written months map to the same semantic anchors, so `May 2023`, `2023年5月`, and `January 5, 1914` versus `1914年1月5日` agree. The same mechanism covers linked chapter numbers, explicit decades, centuries, World War ordinals, and scaled quantities. Balanced mode keeps a missing source anchor blocking but treats a target-only anchor as a warning: `May` to `5月` can be source-backed even though the target introduces a digit. Strict mode blocks either direction and is mandatory in the final v1 audit. A modal `may` outside date syntax is not converted, and all unrelated year/day/value anchors remain independently required.

A source acronym may be replaced by an approved preferred translation or allowed variant in the evidence-backed glossary—for example, `US` may validly become `美国`. Word-like Latin glossary terms are matched at token boundaries, preventing short entries from being triggered by unrelated substrings such as `US` inside `purposes`.

## Online adapter boundary

The optional OpenAI adapter uses the Responses API with a strict JSON Schema requiring one translation per source item. It owns credentials, request pacing, and bounded retries for transient failures. The pipeline commits every completed unit before the next call, so a later failure resumes without repeating completed work.

Image-only Markdown Segments contain structure but no prose. The pipeline records them through the deterministic `structural-passthrough` adapter and preserves the exact Markdown instead of spending a model request on the alt-text token. Mixed units send only their prose Segments to the selected model while retaining one-to-one TranslationRecords for every source Segment.

## Codex Skill surface

`skills/contextweaver-translate` is the agent-facing orchestration layer. It instructs Codex to inspect state before mutation, use the CLI as the durable execution layer, generate or reuse the automatic translation brief, exchange bounded `agent-batch` work packages, preserve revision history, and validate before export. Its read-only inspection script emits JSON so agents can determine the next safe step without parsing human-oriented logs. The Skill contains no provider credentials and does not bypass CLI invariants.

## Output rendering

Export selection is the Cartesian choice of format (`markdown`, `epub`, or both) and content (`translated`, `bilingual`, or both). Every route uses the newest active TranslationRecord and the same pre-export validation gate. EPUB output contains metadata, navigation, CSS, and one XHTML chapter per non-empty Section. Markdown is rendered with embedded HTML disabled. Source image references are downgraded to labeled text placeholders until the importer can copy and rewrite binary assets safely.

`state/export_metadata.json` records the source title/language, target language, actual translating Agent/model, optional human-reference credit, and fidelity policy. The same information appears in Markdown front matter, EPUB Dublin Core fields, and a visible EPUB provenance page. Attribution is inferred from active TranslationRecords unless explicitly overridden; mock output is labeled as non-final.

## Known phase-one limits

Nested Markdown constructs remain one top-level Segment. DOCX/EPUB normalization omits images and some footnote, hyperlink, nested-table, and style details. Knowledge extraction is conservative and oriented toward capitalized names. Deterministic rules cannot judge semantic fidelity or literary quality.

The v1.0 completion gate is maintained in [v1-acceptance.md](v1-acceptance.md); new feature work should be judged against those exit criteria rather than expanding the framework indefinitely.
