---
name: contextweaver-translate
description: Operate reviewable, resumable long-form translation projects with ContextWeaver. Use when Codex needs to import or translate a book, EPUB, DOCX, Markdown, TXT, long report, or other context-dependent document; inspect translation progress; manage glossary or entity evidence; resume interrupted work; selectively retranslate segments, sections, or terminology; validate alignment and formatting; or export translated and bilingual Markdown.
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

4. Run `extract-knowledge`. Review `state/glossary.csv` and `state/entities.jsonl`. Keep candidates `proposed` until a human or explicit user instruction approves the translation/classification. Read [references/review-files.md](references/review-files.md) when editing these files.

5. Use `translate --adapter mock` for workflow verification. Use `--adapter openai` only when the user requests online translation and `OPENAI_API_KEY` is available. Never print or inspect the key. Set a conservative `--requests-per-minute` for long runs.

6. Run `validate` after every translation or knowledge change. Treat exit code 1 as review work, not a command failure. Read `state/issues.jsonl`; do not silently waive errors.

7. Run `export` only after validation has no errors. Present both `output/translated.md` and `output/bilingual.md` for review.

8. Run `status` and summarize completed steps, counts, open issues, and output paths.

## Resume and revise

- Re-run normal `translate` to skip completed segments and resume pending work.
- Use `--segment`, `--section`, or `--term` only for intentional retranslation. Always pass a concise `--reason`.
- Preserve all TranslationRecords. A new revision must point to its predecessor through `supersedes`.
- Run `migrate` before modifying a schema-v1 project. Never hand-edit `schema_version`.

## Safety and review rules

- Inspect the original and normalized `source/document.md` when import fidelity matters.
- Stop and report unsupported or damaged structures instead of guessing.
- Preserve Markdown markers, footnote references, list shape, tables, and block quotes.
- Keep proposed terms/entities out of model context until approved.
- Record ambiguous names, pronouns, terminology, or source defects as review issues or notes.
- Prefer one small verified pipeline step at a time. Re-run `status` after a failed or interrupted command.

For persisted fields and status meanings, read [references/project-schema.md](references/project-schema.md).

