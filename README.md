# ContextWeaver

ContextWeaver is an early-stage, file-first engineering framework for translating books, long reports, and other context-dependent documents with coding agents or language models. It is designed to make translation state inspectable, resumable, and safe to revise.

Ordinary chunk-by-chunk machine translation treats each block as an isolated prompt. ContextWeaver instead gives every translation unit a compact context packet: neighboring text, section context, glossary entries, and cross-chapter entities. Stable segment identifiers preserve source-to-translation alignment, while a manifest and append-only translation records allow interrupted runs to resume without retranslating completed work.

The current release imports Markdown, TXT, DOCX, and EPUB; preserves reviewable Markdown blocks; creates stable segments and units; proposes evidence-backed terminology and entities; runs an offline mock or optional OpenAI adapter; keeps immutable translation revisions; validates alignment, structure, terminology, and repeated-source consistency; and exports translated or bilingual Markdown.

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
contextweaver extract-knowledge my-book
contextweaver translate my-book --adapter mock
contextweaver validate my-book
contextweaver export my-book
contextweaver status my-book
```

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

## Project data

A generated translation project is intentionally readable:

```text
my-book/
├── project.json
├── source/document.md
├── state/
│   ├── manifest.json
│   ├── source_document.json
│   ├── sections.jsonl
│   ├── segments.jsonl
│   ├── units.jsonl
│   ├── translations.jsonl
│   ├── issues.jsonl
│   ├── glossary.csv
│   └── entities.jsonl
├── notes/
└── output/
    ├── translated.md
    └── bilingual.md
```

`source/original.*` retains the imported artifact and `source/document.md` is its transparent normalized representation. Glossary and entity records contain review status and source Segment evidence. Re-running extraction merges new candidates without overwriting reviewed rows.

Generated structural files are atomically rewritten. Translation records are appended, completed Segment IDs are skipped on later runs, and selective retranslation adds `revision`, `supersedes`, and `reason`. Export is blocked when validation has errors. Importing a different source requires `--replace`. Existing schema-v1 projects can be upgraded with `contextweaver migrate PROJECT`.

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
- Add chapter summaries, ambiguity tracking, and style-profile checks.
- Add provider-neutral prompt templates and more opt-in adapters.
- Add revision comparison/approval commands and richer export formats.
- Add multi-agent criticism/revision workflows, GUI, and API surfaces.

## Status

ContextWeaver is pre-alpha. DOCX and EPUB normalization does not preserve every layout feature. Heuristic proposals and deterministic checks assist human review; they are not semantic quality guarantees. File schemas evolve through explicit migrations. Do not use mock output as a real translation.

## License

MIT. Future borrowing from related projects must be license-checked and documented; this initial implementation was designed independently.
