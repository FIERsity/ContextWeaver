# Architecture and invariants

ContextWeaver separates durable domain state from orchestration and provider calls.

1. Import retains the original artifact, normalizes it to Markdown, and records its SHA-256 digest.
2. Segmentation parses source-preserving Markdown blocks, then deterministically derives section, segment, and unit IDs.
3. Context assembly selects only the unit's source segments, immediate neighbors, optional section summary, glossary, and entity records.
4. An adapter returns exactly one string per requested segment. Cardinality and empty output are treated as hard errors.
5. Translation records are appended and completed Segment IDs are skipped. Selected segments append linked revisions.
6. Validation selects the newest revision, requires complete alignment, and checks structure, terminology, suspicious length, and repeated-source consistency.

## Stable identity

IDs use truncated SHA-256 values over namespaced inputs. Segment identity includes the imported document digest, section identity, source ordinal, and normalized text. The same imported bytes and segmentation algorithm therefore reproduce the same IDs. A changed source is a new document; it must not silently inherit translations from an older source.

## Persistence

`project.json` and `manifest.json` describe the project and progress. Structural collections use JSONL, glossary data uses CSV, and exported documents use Markdown. Generated structural collections are written through a temporary file and atomically replaced. Translation records are append-only in the normal flow. Readers reject unknown fields so schema drift fails visibly rather than corrupting state.

SQLite is intentionally absent: phase-one state is small enough for transparent files, Git diffs are useful during review, and no transactional cross-process scheduling is needed yet. A future index or queue may use SQLite as a derived cache while retaining exportable canonical records.

## Safe evolution

`schema_version` is currently `2`. The `migrate` command upgrades v1 records with default structural and revision metadata without changing IDs. Further stored-format or ID changes require another migration and compatibility fixtures. Model-specific prompts, credentials, retry policies, and rate limits belong in adapter modules, not domain records.

## Import and structure preservation

Markdown-it token ranges retain each top-level block's raw Markdown, plain text, type, source line locator, and format signature. TXT headings are normalized to Markdown. DOCX headings, emphasis, simple lists, and tables are converted with `python-docx`; EPUB spine documents are converted with EbookLib and Beautiful Soup. The original file remains available to audit lossy conversion.

## Human-reviewed knowledge

`extract-knowledge` conservatively proposes repeated proper-name candidates. Glossary and entity records include confidence, review status, and evidence Segment IDs. Only approved records enter context packets. Extraction merges new candidates rather than overwriting human decisions.

## Online adapter boundary

The optional OpenAI adapter uses the Responses API with a strict JSON Schema requiring one translation per source item. It owns credentials, request pacing, and bounded retries for transient failures. The pipeline commits every completed unit before the next call, so a later failure resumes without repeating completed work.

## Codex Skill surface

`skills/contextweaver-translate` is the agent-facing orchestration layer. It instructs Codex to inspect state before mutation, use the CLI as the durable execution layer, pause for glossary/entity review, preserve revision history, and validate before export. Its read-only inspection script emits JSON so agents can determine the next safe step without parsing human-oriented logs. The Skill contains no provider credentials and does not bypass CLI invariants.

## Known phase-one limits

Nested Markdown constructs remain one top-level Segment. DOCX/EPUB normalization omits images and some footnote, hyperlink, nested-table, and style details. Knowledge extraction is conservative and oriented toward capitalized names. Deterministic rules cannot judge semantic fidelity or literary quality.
