# ContextWeaver

ContextWeaver is an early-stage, file-first engineering framework for translating books, long reports, and other context-dependent documents with coding agents or language models. It is designed to make translation state inspectable, resumable, and safe to revise.

Ordinary chunk-by-chunk machine translation treats each block as an isolated prompt. ContextWeaver instead gives every translation unit a compact context packet: neighboring text, section context, glossary entries, and cross-chapter entities. Stable segment identifiers preserve source-to-translation alignment, while a manifest and append-only translation records allow interrupted runs to resume without retranslating completed work.

The current release imports Markdown, TXT, DOCX, and EPUB; preserves reviewable Markdown blocks; creates stable segments and units; automatically profiles a work before translation; proposes evidence-backed terminology and entities; runs an offline mock or optional OpenAI adapter; keeps immutable translation revisions; validates alignment, structure, terminology, and repeated-source consistency; and exports translated or bilingual Markdown and EPUB.

Version 0.3 adds import-loss reports and local human-translation references, including chapter alignment and review-draft adaptation from Taiwan Traditional Chinese to Mainland Simplified Chinese. See the structural, non-copyrighted [Power and Progress pilot report](docs/pilots/power-and-progress.md).

Version 0.4 introduces the Agent-first path: automatic work profiling, evidence-backed concept strategy, strategy-aware ContextPackets, and a resumable `auto` command that does not require human approval.

Version 0.5 adds an append-only Agent Critic/Reviser pass. Every review binds an exact input TranslationRecord to its accepted or revised output, and `auto` runs this pass before validation and export by default.

Version 0.6 adds bounded chapter-level and whole-book coherence review with scope fingerprints, evidence dossiers, and multi-Segment revision support. The [v1.0 acceptance target](docs/v1-acceptance.md) defines when the project is ready to stop expanding and ship.

Version 0.7 adds resumable Section summaries and conservative ambiguity records. Summaries carry source/strategy fingerprints and revision links, enter every ContextPacket, and provide chapter context to Section/book review without making human resolution a prerequisite.

Version 0.8 adds a machine-readable v1 readiness audit and convergent autonomous review. `auto` repeats Segment, Section, and book review until a round produces no new revisions, then validates, exports, and records whether every v1 completion gate is actually satisfied.

Version 0.9 adds revision-tracked Section-title translation, localized Markdown/EPUB headings and navigation, source-title integrity checks, coherence invalidation after title edits, structural image passthrough, evidence auditing, and cost-bounded TranslationUnit batches.

Version 0.10 adds bounded offline-Agent work packages and semantic numeric anchors for natural, source-backed Chinese renderings of dates, decades, centuries, historical ordinals, and scaled quantities.

The current EPUB exporter also copies referenced image binaries from an EPUB source and rewrites resolvable intra-book chapter links to the generated EPUB sections. Export auditing verifies that image targets and local links resolve inside both EPUB artifacts.

## Quick start

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
# Optional online adapter:
python -m pip install -e '.[openai]'

contextweaver init my-book --name "My Book" --source-language en --target-language zh-CN
contextweaver import my-book examples/sample-book.md
contextweaver segment my-book --unit-size 2
contextweaver analyze my-book --adapter heuristic
contextweaver summarize my-book --adapter heuristic
contextweaver extract-knowledge my-book
contextweaver translate-titles my-book --adapter mock
contextweaver reference-import my-book human-translation.epub --language zh-TW
contextweaver reference-simplify my-book --format all
contextweaver translate my-book --adapter mock
contextweaver review my-book --adapter heuristic
contextweaver coherence-review my-book --adapter heuristic --scope all
contextweaver validate my-book
contextweaver export my-book
contextweaver audit my-book
contextweaver status my-book
```

The primary Agent-first route requires no human approval gate. After import, one resumable command performs segmentation when needed, book analysis, knowledge extraction, translation, validation, and export:

```bash
contextweaver auto my-book --adapter mock
# With the optional online adapter:
contextweaver auto my-book --adapter openai --model gpt-5.6-sol \
  --requests-per-minute 30 --format all --content all
# Cost-controlled resumable batches for a long pilot:
contextweaver auto my-book --adapter openai --max-units 10
```

`auto` writes `state/translation_brief.json` and a readable mirror at `notes/translation_brief.md`. The strategy describes genre, disciplinary register, source and target style, audience, translation principles, and evidence-backed concept rules. It is injected into every ContextPacket. After translation, the default Critic/Reviser pass checks semantic fidelity, concept sense, terminology, rhetoric, formatting, and natural Chinese. Segment, Section, and book review repeat until a full round produces no new revision, with `--max-review-rounds` preventing unbounded churn. Human editing is optional; normal reruns preserve the existing brief, while `--refresh-analysis` explicitly regenerates it. Use `--skip-review` only when intentionally trading quality for cost or a workflow test.

For a costly long-book run, `--max-units N` processes at most N currently pending TranslationUnits and exits successfully with durable records. Repeating the same command resumes from the next pending unit. A bounded incomplete run never starts Section/book review, validation, or export; omitting the limit eventually follows the normal full completion path.

The review stage is independently resumable and scope-selectable:

```bash
contextweaver review my-book --adapter openai --model gpt-5.6-sol
contextweaver review my-book --adapter heuristic --section sec_...
```

`state/reviews.jsonl` records the exact input and output TranslationRecord IDs, verdict, issue categories, rationale, confidence, reviewer, and model. A Reviser must return a complete changed translation; accepted revisions append to `translations.jsonl` with `supersedes` rather than overwriting history.

When the final strict audit finds a deterministic failure, export only the affected current records as a bounded repair package. It includes the exact source, current translation, failure evidence, and ContextPacket; the Agent returns the standard two-field draft, which re-enters through the normal append-only import path:

```bash
contextweaver audit-repair-batch my-book work/audit-repair.jsonl --max-segments 25
contextweaver translation-import my-book work/repaired.jsonl \
  --adapter codex-agent --model GPT-5 --reason strict-audit-repair
```

For a target-only numeric anchor that the Agent can explicitly trace to source context, it may instead append a source-backed decision. The decision is bound to both the exact issue ID and the current TranslationRecord, so any later retranslation invalidates it automatically:

```bash
contextweaver audit-resolution-import my-book work/source-backed.jsonl --model GPT-5
```

Chapter and whole-book review use bounded dossiers instead of sending the complete source repeatedly. Section dossiers combine stratified coverage with every sampled high-risk concept occurrence. The book dossier combines representative passages from every Section with a cross-book concept concordance. Scope reviews are fingerprinted from active TranslationRecord IDs, so an unchanged chapter or book is skipped on resume while any later revision automatically invalidates the relevant review:

```bash
contextweaver coherence-review my-book --scope section --section sec_... --adapter openai
contextweaver coherence-review my-book --scope book --adapter openai
contextweaver coherence-review my-book --scope all --adapter heuristic
```

Section context is generated before translation and can be run independently:

```bash
contextweaver summarize my-book --adapter openai --model gpt-5.6-sol \
  --requests-per-minute 30
contextweaver summarize my-book --section sec_... --refresh
```

`state/section_summaries.jsonl` is append-only and links revisions through `supersedes`. Its digest includes the source Segment identities and current translation strategy, so unchanged work resumes immediately while a strategy change makes the summary eligible for regeneration. Genuine unresolved references, terms, entities, source defects, or rhetoric are stored in `state/ambiguities.jsonl`. They inform later review but do not impose a mandatory human gate.

The final gate is explicit and independently runnable:

```bash
contextweaver audit my-book
```

It writes `state/v1_audit.json` and `notes/v1_audit.md`, checking source retention, structural identity, strategy, summary and knowledge-evidence coverage, revision integrity, current three-level review fingerprints, deterministic validation, all four final artifacts, EPUB readback, and provenance. `--allow-mock` exists only for workflow tests; it must not be used as release evidence.

## Use with Codex

The repository includes the [`contextweaver-translate`](skills/contextweaver-translate/SKILL.md) Skill. Install it by linking the versioned Skill into your personal Codex directory:

```bash
ln -s "$(pwd)/skills/contextweaver-translate" ~/.codex/skills/contextweaver-translate
```

Start a new Codex task after installation, then invoke it explicitly:

```text
Use $contextweaver-translate to translate this EPUB into Chinese, review terminology proposals, validate it, and export bilingual Markdown.
```

Codex will inspect project state before mutation, run one resumable step at a time, keep glossary/entity decisions in reviewable files, and avoid online translation unless requested. The Skill source remains in this repository so its workflow and the CLI version evolve together.

The mock adapter copies each source segment with a `[MOCK]` prefix, so the complete workflow works without an API key. Run the repository example with:

```bash
python examples/run_demo.py
```

For online translation, set `OPENAI_API_KEY` and use the optional adapter. Requests are paced and transient failures are retried:

```bash
contextweaver translate my-book --adapter openai --model gpt-5.6-sol --requests-per-minute 30
```

Selective retranslation appends a linked immutable revision:

```bash
contextweaver translate my-book --segment seg_... --reason terminology-fix
contextweaver translate my-book --section sec_... --reason chapter-review
contextweaver translate my-book --term ContextWeaver --reason glossary-update
```

Codex or another offline Agent can import a strict, reviewable JSONL draft without pretending an online API was used:

```bash
contextweaver agent-batch my-book agent-work.jsonl \
  --section sec_...
contextweaver translation-import my-book draft.jsonl \
  --adapter codex-agent --model "GPT-5" --reason chapter-pilot
contextweaver validate my-book --segment seg_... --segment seg_...
contextweaver export my-book --format all --content all --segment seg_...
```

`agent-batch` exports only pending TranslationUnits and includes their bounded ContextPackets, Section identity, source/target languages, strategy, summary, neighbors, approved knowledge, and optional reference evidence. It refuses to overwrite an existing package unless `--force` is explicit. The Agent's returned draft remains deliberately strict: each row contains only `segment_id` and `translated_text`. Scoped validation/export allows a unit or chapter pilot to complete without treating the rest of the book as translated.

When `--max-units` is omitted, `agent-batch` derives its budgets from the model context before selecting work. The editable operational default is a 400,000-token window: 25% source, 35% expected target, 25% shared instructions/context, and 15% safety. The first three shares are a planning envelope, not rigid partitions: after reserving 15%, the selector fits estimated serialized input plus expected Chinese output into the remaining 85%, allowing unused input/output capacity to be borrowed. It assumes four input characters per token and 0.6 target tokens per English source character, retains a 400,000-character raw-source guardrail, and uses 500 TranslationUnits as a secondary ceiling. It prefers one complete Section and never crosses a Section boundary, but splits an oversized Section at a TranslationUnit boundary. Pass the real model limit with `--context-window-tokens`; use `--target-source-chars` or `--max-units` only as explicit overrides. `state/batch_strategy.json` records every assumption, derived limit, and actual package metric.

Numeric validation defaults to `--numeric-mode balanced`: a number present in the source but missing from the translation remains an error, while a target-only numeric anchor is a review warning because it may be a legitimate explicit rendering of source evidence such as `May` to `5月`. `--numeric-mode strict` blocks every unresolved mismatch, and the v1 release audit always uses strict mode.

For autonomous book-scale work, create one durable Campaign rather than treating a package as the total assignment:

```bash
contextweaver agent-campaign my-book
contextweaver agent-batch my-book next-checkpoint.jsonl
```

`agent-campaign` records every targeted pending Segment in `state/agent_campaign.json` without expanding all ContextPackets into memory. It uses the same model-context-derived budget as `agent-batch`; pass `--context-window-tokens` when the active model differs from the operational default. Re-running it refreshes completed and in-progress counts; `--refresh` is required to replace its scope. An Agent should loop over adaptive `agent-batch`, strict `translation-import`, review, and validation until the Campaign is complete. Thus a Campaign can cover hundreds or thousands of Segments while each failure-recovery surface remains bounded.

Section headings have a separate append-only revision chain so translated books do not retain English chapter titles or destabilize Section/Segment IDs:

```bash
contextweaver translate-titles my-book --adapter openai
contextweaver translate-titles my-book --section sec_... --refresh \
  --reason chapter-title-style-fix
contextweaver section-title-import my-book title-draft.jsonl \
  --adapter codex-agent --model "GPT-5" --reason mainland-title-review
```

Each title-draft row contains only `section_id` and `translated_title`. Translated Markdown/EPUB uses the current target title; bilingual output preserves both source and target titles. Title revisions invalidate affected Section/book coherence fingerprints.

## Project data

A generated translation project is intentionally readable:

```text
my-book/
├── project.json
├── source/document.md
├── state/
│   ├── manifest.json
│   ├── translation_brief.json
│   ├── source_document.json
│   ├── sections.jsonl
│   ├── segments.jsonl
│   ├── units.jsonl
│   ├── translations.jsonl
│   ├── section_titles.jsonl
│   ├── reviews.jsonl
│   ├── scope_reviews.jsonl
│   ├── section_summaries.jsonl
│   ├── ambiguities.jsonl
│   ├── v1_audit.json
│   ├── issues.jsonl
│   ├── glossary.csv
│   └── entities.jsonl
├── notes/
│   ├── translation_brief.md
│   ├── section_summaries.md
│   └── v1_audit.md
└── output/
    ├── translated.md
    └── bilingual.md
```

`source/original.*` retains the imported artifact and `source/document.md` is its transparent normalized representation. The automatically generated translation brief is immediately usable without approval and remains editable. Glossary and entity records contain review status and source Segment evidence. Re-running extraction merges new candidates without overwriting reviewed rows.

An optional local human translation can be imported as reference evidence. Main chapters are aligned by explicit chapter keys, and ContextPackets receive only a small proportional reference window. Taiwan Traditional Chinese references can be converted with OpenCC `tw2sp` into an explicitly unapproved Mainland Simplified draft. Original and adapted reference texts remain separate. Imported copyrighted books and generated adaptations should stay outside version control unless redistribution rights are confirmed.

Exports are opt-in by format and content. The default remains both translated and bilingual Markdown for compatibility:

```bash
contextweaver export my-book --format markdown --content translated
contextweaver export my-book --format epub --content bilingual
contextweaver export my-book --format all --content all \
  --translator "Codex Agent using GPT-5.6" \
  --reference-credit "Human translator, consulted edition"
```

Generated EPUB files include metadata, navigation, one XHTML document per non-empty Section, basic typography, image binaries referenced by the imported EPUB, and rewritten resolvable chapter links. An image reference that cannot be resolved unambiguously is rendered as an explicit text placeholder rather than a broken link, and the final audit reports the missing resource coverage.

Image-only Markdown Segments bypass the model through a deterministic structural passthrough, preserving their exact source marker and stable alignment without wasting translation calls. EPUB-backed images are copied into EPUB exports; standalone Markdown image references remain explicit placeholders unless their source files are added through a future asset-import path.

Final exports embed translation provenance in Markdown front matter, EPUB Dublin Core metadata, and a visible EPUB provenance page. The actual Agent/model is credited as translator; a consulted human edition is credited separately as translation reference. The source-language Segment is always authoritative. The locale-adapted reference export explicitly identifies itself as an OpenCC transformation, not a new translation from the original.

Generated structural files are atomically rewritten. Translation records are appended, completed Segment IDs are skipped on later runs, and selective retranslation adds `revision`, `supersedes`, and `reason`. Export is blocked when validation has errors. Importing a different source requires `--replace`. Existing schema-v1 projects can be upgraded with `contextweaver migrate PROJECT`.

Numeric validation compares normalized information rather than raw character spelling: for example, the date forms `May 2023`, `2023年5月`, and `2023年五月` share the same month anchor. This permits natural Chinese date rendering without weakening checks for genuinely missing or invented values.

## Source layout

```text
src/contextweaver/
├── models.py       # domain records
├── storage.py      # strict JSON/JSONL persistence
├── pipeline.py     # idempotent workflow operations
├── adapters.py     # provider-neutral interface and mock
├── importers.py    # DOCX/EPUB/TXT normalization
├── markdown.py     # source-preserving block parser
├── knowledge.py    # evidence-backed review proposals
├── strategy.py     # automatic book profiling and concept strategy
├── review.py       # append-only Agent criticism and revision
├── coherence.py    # bounded section/book review and scope fingerprints
├── coherence_adapters.py
├── summaries.py    # resumable chapter context and ambiguity records
├── summary_adapters.py
├── audit.py        # evidence-backed v1 completion gate
├── validation.py   # deterministic quality checks
└── cli.py          # command presentation and error handling
skills/contextweaver-translate/
├── SKILL.md        # Codex workflow and safety rules
├── agents/         # Codex UI metadata
├── references/     # project schema and review guidance
└── scripts/        # read-only project inspection
```

See [docs/architecture.md](docs/architecture.md) for invariants and extension points, and [CONTRIBUTING.md](CONTRIBUTING.md) before making changes.

## Roadmap

- Preserve richer DOCX/EPUB images, footnotes, hyperlinks, and nested tables.
- Complete a full real-book autonomous translation and acceptance audit.
- Add autonomous ambiguity resolution and richer style-profile checks.
- Add provider-neutral prompt templates and more opt-in adapters.
- Add revision comparison/approval commands and richer export formats.
- Add GUI and API surfaces after the v1 acceptance gate passes.

## Status

ContextWeaver is pre-alpha. DOCX and EPUB normalization does not preserve every layout feature. Heuristic proposals and deterministic checks assist human review; they are not semantic quality guarantees. File schemas evolve through explicit migrations. Do not use mock output as a real translation.

## License

MIT. Future borrowing from related projects must be license-checked and documented; this initial implementation was designed independently.
