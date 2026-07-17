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

2. Import one source. Never pass `--replace` unless the user explicitly intends to discard generated translation state. EPUB, DOCX, Markdown, and TXT are supported.

3. Run `segment`, then inspect `state/segments.jsonl` before translating. Report section, segment, and unit counts. Do not alter stable Segment IDs manually.

4. Run `analyze` before translation. It generates `state/translation_brief.json` and `notes/translation_brief.md` from bounded samples across the work. Use the result immediately; human review is optional. Reuse an existing brief on resume and use `--refresh` only when intentionally replacing its current strategy.

5. Run `summarize` to generate append-only Section summaries and conservative ambiguity records before translation. Reuse matching source/strategy fingerprints on resume; use `--refresh` only when intentionally replacing current summary context. Open ambiguities inform later review but never create a mandatory human gate. Run `translate-titles` for an online/mock workflow, or `section-title-import` for Codex-produced titles. Use title `--refresh` only with an explicit reason; it appends a revision and invalidates affected coherence reviews. Never edit `Section.title` or stable IDs to localize headings.

6. Run `extract-knowledge`. Keep uncertain candidates `proposed`; proposed rows do not block automatic translation. Agent or human review may approve them later. Read [references/review-files.md](references/review-files.md) when editing these files.

   When the user provides a licensed or locally available human translation, run `reference-import PROJECT FILE --language LANGUAGE --credit "TRANSLATOR (reference only)"`. Inspect chapter alignments and both import reports. For a Taiwan Traditional Chinese reference targeting Mainland readers, run `reference-simplify`; treat the result as a locale-adapted draft reference, never as a new source-faithful translation.

7. Use `translate --adapter mock` for workflow verification. Use `--adapter openai` only when the user requests online translation and `OPENAI_API_KEY` is available. Never print or inspect the key. Set a conservative `--requests-per-minute` for long runs. For autonomous end-to-end operation after import, use `auto`; it safely resumes analysis, summaries, segmentation, knowledge extraction, pending translation, convergent Agent review, validation, export, and audit without requiring human approval. For a real-book trial or a cost-bounded session, pass `--max-units N`; rerun to resume. An incomplete bounded run must stop before Section/book review and export. Keep the default review limit unless a costly real run justifies an explicit `--max-review-rounds` value.

   When Codex itself produces translations without an online adapter, run `agent-campaign PROJECT` first so the assignment covers the complete pending book rather than one small package. Then run `agent-batch PROJECT WORK.jsonl` and normally accept the adaptive, chapter-bounded checkpoint. It targets about 40,000 source characters and no more than 30 TranslationUnits (usually about 90 Segments); inspect `state/agent_campaign.json` for the full Campaign and `state/batch_strategy.json` for the current checkpoint. Use explicit `--max-units N` only for early style calibration, a user-specified cap, or a deliberately monitored high-throughput run. Read each independently bounded ContextPacket and return strict JSONL rows containing only `segment_id` and `translated_text`, then run `translation-import PROJECT DRAFT --adapter codex-agent --model MODEL --reason REASON`. Review and validate the checkpoint, rerun `agent-campaign PROJECT` to refresh progress, and continue immediately with the next checkpoint until the Campaign is complete or a real blocker occurs. Re-running `agent-batch` to a new path omits active translations; replacing an existing package requires explicit `--force`. Write Section-title rows separately with only `section_id` and `translated_title`, then use `section-title-import`. Keep work packages and drafts inside the ignored project directory. Never fabricate a model name.

8. Run `review` after translation. The Critic/Reviser must compare the exact source and active TranslationRecord using the strategy and context, then append its decision to `state/reviews.jsonl`. A revision must be a complete changed translation and must append a linked TranslationRecord; never overwrite the reviewed input. Normal reruns skip already reviewed versions.

9. Run `coherence-review --scope section` after Segment review, then `coherence-review --scope book` after all Sections are complete. These passes use bounded evidence dossiers, current Section summaries, open ambiguity records, and active-translation fingerprints; they may revise only included evidence Segments. Do not run book review on an incomplete project. After any revision, repeat Segment, Section, and book review until a complete round produces no revision. `auto` performs this convergence loop by default and fails instead of silently accepting endless churn.

10. Run `validate` after every translation, review, or knowledge change. Use repeatable `--segment` or `--section` for an incomplete pilot; scoped issues are stored separately and do not mark the whole book complete. Treat exit code 1 as review work, not a command failure. Do not silently waive errors.

11. Run `export` only after validation has no errors. Use `--format markdown|epub|all` and `--content translated|bilingual|all`; an autonomous request may choose both without pausing for confirmation. Use `--translator` for the actual translating Agent/model and `--reference-credit` for any consulted human edition. Never credit a locale converter as translator of a source-faithful edition. Report that unresolved source images become explicit text placeholders in generated EPUB until asset copying is implemented.

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
