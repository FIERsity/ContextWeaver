# Power and Progress local pilot

This report contains structural statistics only. The books and generated text are excluded from Git.

## Inputs

- English EPUB: 62 readable spine documents, 3,011 paragraphs, 41 images, and 703 links.
- Taiwan Traditional Chinese human translation: 54 readable spine documents, 3,170 paragraphs, 109 images, 1,283 links, and 545 footnote-like links.

## ContextWeaver output

- English source: 20 Sections, 3,025 Segments, and 1,015 TranslationUnits.
- Human reference: 165 Sections and 3,246 Segments.
- Chapter alignment: prologue plus chapters 1–11, all 12 matched by explicit chapter key.
- Locale adaptation: 3,246 draft zh-CN reference records using OpenCC `tw2sp`.
- Reader artifact: a 649 KiB zh-CN EPUB with 163 content chapters plus navigation was generated and reopened successfully with EbookLib.
- Reference coverage: 659 of 1,015 TranslationUnits (64.9%); uncovered units are unpaired front matter and back matter.
- Full ContextPacket traversal: reduced from about 20 seconds to about 0.3 seconds after adding modification-aware in-process indexes.

## Findings

The English edition encodes chapter numbers and titles as CSS-classed paragraphs rather than semantic heading elements. Supporting `cn` and `ct` classes changed the book from a nearly flat parse to a chapter-aware structure. The two editions have different spine layouts and subsection counts, so file-to-file pairing is invalid. Chapter-bounded proportional reference windows are a useful bootstrap, but they are not paragraph-level semantic alignments.

Import reports now expose image, link, and footnote risks. Images are represented as Markdown references, but binary asset copying and robust EPUB footnote reconstruction remain unfinished. The generated Simplified Chinese edition is a locale-adaptation reference draft, not a reviewed translation or redistributable artifact.

The regenerated reference files explicitly credit Lin Junhong (林俊宏) as translator of the consulted Taiwan edition and identify ContextWeaver OpenCC `tw2sp` only as the locale adaptation tool. A future source-faithful edition must credit the actual translating Agent/model and treat this human edition as reference only.

## Source-faithful Prologue pilot

All 33 Prologue Segments were translated anew from English by the local Codex Agent and imported with adapter `codex-agent` and model `GPT-5`. The active complete revision uses prompt version `translate-v3-source-faithful-natural-zh`: English remains the sole semantic authority, while clause order, sentence boundaries, subjects, transitions, and punctuation may be reshaped into idiomatic Mainland Chinese without changing facts, qualifications, argument relations, tone, or rhetoric.

The pilot now has an automatic work profile with eight high-impact concept rules, current summaries for all 20 source Sections, 33 source-aligned Agent review records, and a fingerprinted Prologue coherence review. Repeating summary, Segment-review, and Section-review commands skips unchanged versions. Scoped deterministic validation reports zero issues. Translated and bilingual Markdown/EPUB artifacts were generated with `Codex Agent (GPT-5)` as translator, Lin Junhong as reference translator, and *Power and Progress* as the authoritative source. Copyrighted pilot artifacts remain excluded from Git.

## Current whole-book progress

The durable project currently has 142 of 3,025 active source-aligned translations and 142 matching Segment reviews. This comprises the complete 33-Segment Prologue, all 37 Segments across the copyright/title, Contents, and Navigation/dedication Sections, and the first 72 Segments of Chapter 1. Three image-only Segments use the deterministic structural passthrough without a model call. All four complete Sections have current coherence-review fingerprints, and scoped deterministic validation reports zero issues for both the completed Sections and the translated Chapter 1 range. The Chapter 1 range is available as translated and bilingual Markdown/EPUB for reading while the rest of the chapter remains pending.

Four approved entity records now preserve evidence for the two authors and the PublicAffairs/Hachette publishing identities, including the distinction between preferred Mainland author names and names found in the consulted Taiwan edition. All 20 Section titles have source-digest-bound `codex-agent/GPT-5` records, including reader-facing Mainland chapter names. Translated EPUB navigation uses only these target titles; bilingual Markdown shows source and target titles together. The v1 audit verifies every concept, terminology, entity, and Section-title source binding. It currently passes 13 checks and fails 7 completion checks; it remains correctly not ready because full Segment/Section/book review coverage and whole-book artifacts are incomplete.

The front-matter pilot also changed numeric validation policy based on a real revision chain. `May 2023` was first rendered as `2023年5月`, then temporarily changed to `2023年五月` after a raw digit comparison flagged the `5`. The validator now canonicalizes explicit calendar-month information, allowing both natural Chinese forms while still checking the year and all unrelated numeric anchors. The active revision is again the more natural `2023年5月`; all three revisions remain traceable.

The next Chapter 1 batch extended that rule without introducing general-purpose number guessing. Explicit transformations such as `1980s` to `20世纪80年代`, `twentieth century` to `20世纪`, `World War II` to `第二次世界大战`, and `1.5 million` to `150万` now share semantic numeric anchors. The 30-Segment batch was exported through the versioned offline-Agent work-package contract, imported as immutable records, reviewed, and validated with zero scoped issues. Regenerating a new work package then resumed at the next pending Segment.

A second 30-Segment work-package cycle exercised linked chapter references, century notation, and full dates. `chapters 5 through 9` now agrees with `第五章至第九章`, `1700s` with `18世纪`, and `January 5, 1914` with `1914年1月5日`. Source acronyms such as `MRI` and `COVID` remain explicit in the target. Three corrections were appended as revisions rather than overwriting their reviewed inputs; the complete 30-Segment scope then validated with zero issues, and the next package resumed at Segment 73 of Chapter 1.

Chapter 1 added a parallel terminology case: the source acronym `US` is intentionally rendered as the approved Mainland Chinese glossary form `美国`. Acronym validation accepts that evidence-backed rendering, while source-term matching uses Latin token boundaries so the short term does not falsely match words such as `purposes`.
