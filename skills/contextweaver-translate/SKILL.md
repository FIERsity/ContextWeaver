---
name: contextweaver-translate
description: Operate reviewable, resumable long-form translation projects with ContextWeaver. Use when Codex needs to import or translate a book, EPUB, DOCX, Markdown, TXT, long report, or other context-dependent document; inspect translation progress; manage glossary or entity evidence; resume interrupted work; selectively retranslate segments, sections, or terminology; validate alignment and formatting; or export optional translated and bilingual Markdown or EPUB artifacts.
---

# ContextWeaver translation

Use the ContextWeaver CLI as the durable execution layer. Keep decisions in project files rather than only in chat context.

## Locate the CLI

1. Prefer `contextweaver` when installed.
2. In a ContextWeaver source checkout, use `uv run contextweaver`.
3. If neither works, tell the user to install the repository with `python -m pip install -e .`; add `[openai]` only when online translation is requested.

Set a shell variable such as `CW=contextweaver` or `CW="uv run contextweaver"`. Do not use `HOME` or another system variable.

## Run the workflow

1. Inspect before mutation:

   ```bash
   python skills/contextweaver-translate/scripts/inspect_project.py PROJECT
   ```

   If the path is not a project, initialize it with explicit source and target languages.

2. Import one source. Never pass `--replace` unless the user explicitly intends to discard generated translation state. EPUB, DOCX, Markdown, TXT, and JATS XML are supported. For an academic JATS source, inspect `state/import_report.json` before segmenting: figures, tables, citations, equations, footnotes, and references are preserved as reviewable structure, but figure-asset fetching and final PDF/DOCX layout remain a publishing-stage task.

   For an open PLOS ONE JATS source, `academic-assets PROJECT` explicitly fetches only JATS `fig` assets and records their hashes in `state/academic_assets.json`. Install `.[pdf]`, then use `academic-pdf PROJECT --content source` for a source-layout proof, or `--content translated|bilingual` only after the project has complete active translations. The PDF is reflowed A4 with Chinese-capable typography; it is not a journal-template facsimile and does not translate labels embedded in bitmap figures.

3. Run `segment`, then inspect `state/segments.jsonl` before translating. Report section, segment, and unit counts. Do not alter stable Segment IDs manually.

4. Run `analyze` before translation. It generates `state/translation_brief.json` and `notes/translation_brief.md` from bounded samples across the work. Use the result immediately; human review is optional. Reuse an existing brief on resume and use `--refresh` only when intentionally replacing its current strategy.

5. Run `summarize` to generate append-only Section summaries and conservative ambiguity records before translation. Reuse matching source/strategy fingerprints on resume; use `--refresh` only when intentionally replacing current summary context. Open ambiguities inform later review but never create a mandatory human gate. Run `translate-titles` for an online/mock workflow, or `section-title-import` for Codex-produced titles. Use title `--refresh` only with an explicit reason; it appends a revision and invalidates affected coherence reviews. Never edit `Section.title` or stable IDs to localize headings.

6. Run `extract-knowledge`. Keep uncertain candidates `proposed`; proposed rows do not block automatic translation. Agent or human review may approve them later. Read [references/review-files.md](references/review-files.md) when editing these files.

   When the user provides a licensed or locally available human translation, run `reference-import PROJECT FILE --language LANGUAGE --credit "TRANSLATOR (reference only)"`. Inspect chapter alignments and both import reports. For a Taiwan Traditional Chinese reference targeting Mainland readers, run `reference-simplify`; treat the result as a locale-adapted draft reference, never as a new source-faithful translation.

7. Use `translate --adapter mock` for workflow verification. Use `--adapter openai` only when the user requests online translation and `OPENAI_API_KEY` is available. Never print or inspect the key. For an OpenAI-compatible provider that supports Chat Completions rather than the Responses API, use `translate --adapter compatible --base-url URL --model MODEL`; it uses the same durable translation records and JSON output contract. Keep credentials in the shell environment, never in project files. Set a conservative `--requests-per-minute` for long runs. `auto` currently requires the native OpenAI Responses API for its review stages; use resumable `translate` batches plus the normal validation flow for Chat-Completions-only providers. For a real-book trial or a cost-bounded session, pass `--max-units N`; rerun to resume. An incomplete bounded run must stop before Section/book review and export. Keep the default review limit unless a costly real run justifies an explicit `--max-review-rounds` value.

   For a provider with verified spare capacity, `translate --workers 2` overlaps independent TranslationUnits inside the same project lock. The parent process alone appends records, so parallel requests do not create duplicate IDs or overwrite history. Begin at two workers and validate every checkpoint before increasing.

   When Codex itself produces translations without an online adapter, determine the active model's usable context window first, then pass it to `agent-campaign PROJECT --context-window-tokens N`. If exact metadata is unavailable, use the documented 400,000-token operational estimate and record that it is an estimate, not a provider claim. Campaign and checkpoint planning begin with 25% source, 35% target, 25% shared context/instructions, and 15% safety. Keep the safety reserve; let the other shares flex by estimating actual serialized input plus expected target output against the remaining 85%. The planner also applies a raw-source guardrail, complete Section boundaries, and a secondary 500-TranslationUnit ceiling. Run `agent-batch PROJECT WORK.jsonl --context-window-tokens N` and normally accept the largest complete Section that fits; an oversized Section may be split only at a TranslationUnit boundary. Inspect `state/agent_campaign.json` and `state/batch_strategy.json` rather than assuming a fixed Segment count. Use a smaller `--target-source-chars` for costly online runs or early style calibration, and explicit `--max-units N` only for a user-specified cap. Read each independently bounded ContextPacket and return strict JSONL rows containing only `segment_id` and `translated_text`, then run `translation-import PROJECT DRAFT --adapter codex-agent --model MODEL --reason REASON`. Review and validate the checkpoint, rerun `agent-campaign PROJECT` to refresh progress, and continue immediately with the next checkpoint until the Campaign is complete or a real blocker occurs. Re-running `agent-batch` to a new path omits active translations; replacing an existing package requires explicit `--force`. Write Section-title rows separately with only `section_id` and `translated_title`, then use `section-title-import`. Keep work packages and drafts inside the ignored project directory. Never fabricate a model name.

8. Run `review` after translation. The Critic/Reviser must compare the exact source and active TranslationRecord using the strategy and context, then append its decision to `state/reviews.jsonl`. A revision must be a complete changed translation and must append a linked TranslationRecord; never overwrite the reviewed input. Normal reruns skip already reviewed versions.

9. Run `coherence-review --scope section` after Segment review, then `coherence-review --scope book` after all Sections are complete. These passes use bounded evidence dossiers, current Section summaries, open ambiguity records, and active-translation fingerprints; they may revise only included evidence Segments. Do not run book review on an incomplete project. After any revision, repeat Segment, Section, and book review until a complete round produces no revision. `auto` performs this convergence loop by default and fails instead of silently accepting endless churn.

10. Run `validate` after every translation, review, or knowledge change. `relaxed` is the working default: source numbers missing from the translation remain errors, while target-only anchors are deferred because they can be legitimate explicit renderings of source evidence such as `May` to `5月`. Use `--numeric-mode balanced` when target-only anchors should be retained as non-blocking review warnings, and investigate them before publication. Use `--numeric-mode strict` for final release preparation; it blocks every unresolved mismatch. Use repeatable `--segment` or `--section` for an incomplete pilot; scoped issues are stored separately and do not mark the whole book complete. Treat exit code 1 as review work, not a command failure. Do not silently waive errors.

11. Run `export` only after validation has no errors. Use `--format markdown|epub|all` and `--content translated|bilingual|all`; an autonomous request may choose both without pausing for confirmation. Use `--translator` for the actual translating Agent/model and `--reference-credit` for any consulted human edition. Never credit a locale converter as translator of a source-faithful edition. For EPUB inputs, exports copy referenced image binaries and rewrite resolvable local chapter links. Report any unresolved image as an explicit placeholder; the final audit checks local EPUB resource integrity.

12. Run `audit` after final export. Require `ready=true` for a completed book. Never use `--allow-mock` as release evidence; it exists only to exercise the full workflow in tests.

13. Run `status` and summarize completed steps, counts, summary/ambiguity counts, Segment/Section/book review counts, audit pass/fail state, open issues, and output paths.

## Resume and revise

- Re-run normal `translate` to skip completed segments and resume pending work.
- Use `--segment`, `--section`, or `--term` only for intentional retranslation. Always pass a concise `--reason`.
- Preserve all TranslationRecords. A new revision must point to its predecessor through `supersedes`.
- Run `migrate` before modifying a schema-v1 project. Never hand-edit `schema_version`.

## Safety and review rules

- Inspect the original and normalized `source/document.md` when import fidelity matters.
- Stop and report unsupported or damaged structures instead of guessing.
- Preserve Markdown markers, footnote references, list shape, tables, and block quotes.
- Let image-only Segments use the deterministic structural passthrough. Do not send alt-text-only image markers to a semantic translation or review model, and do not credit the passthrough as a translator.
- Treat the imported source-language Segment as the sole authority. If source and reference conflict, follow the source and open a review issue when material.
- For zh-CN, apply source-faithful Chinese naturalization: preserve facts, qualifications, argument relations, tone, and important rhetoric, while allowing clause reordering, sentence splitting or merging, natural subject/transition restoration, and Chinese punctuation. Avoid English-shaped syntax and sentence-by-sentence calques. Naturalization must never become silent addition, omission, explanation, or strengthening/softening of a claim.
- Never commit imported books, human translations, normalized copyrighted text, or generated reference adaptations unless the user confirms redistribution rights.
- Keep proposed terms/entities out of model context until approved.
- Record ambiguous names, pronouns, terminology, or source defects as review issues or notes.
- Prefer one small verified pipeline step at a time. Re-run `status` after a failed or interrupted command.

For persisted fields and status meanings, read [references/project-schema.md](references/project-schema.md).
