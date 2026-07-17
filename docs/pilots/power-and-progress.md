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

The durable project currently has 42 of 3,025 active source-aligned translations and 42 matching Segment reviews. This comprises the 33-Segment Prologue, seven Codex-translated publication/front-matter Segments, and two image-only Segments handled by the deterministic structural passthrough without a model call. Scoped validation for the new front matter reports zero issues.

Four approved entity records now preserve evidence for the two authors and the PublicAffairs/Hachette publishing identities, including the distinction between preferred Mainland author names and names found in the consulted Taiwan edition. The v1 audit verifies that every persisted terminology/entity evidence ID resolves to a current source Segment. The current real-book audit passes 11 checks and fails 7 completion checks; it remains correctly not ready because translation and three-level review coverage are incomplete and full-book artifacts do not yet exist.
