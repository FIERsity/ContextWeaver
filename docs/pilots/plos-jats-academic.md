# PLOS JATS academic-import pilot

This structural pilot uses Heidi Seibold et al., *A computational reproducibility study of PLOS ONE articles featuring longitudinal data analyses* (2021), DOI `10.1371/journal.pone.0251194`.

The article is published by PLOS ONE under CC BY. The downloaded source XML and all generated project state remain in the ignored `.contextweaver-pilots/` directory; this report contains only structural facts and no article text.

## Why this article

It is a compact research article with a formal abstract, nested sections, numbered citations, two figures, four tables, and a reference list. Those features make it a useful first fixture for the academic-import path while avoiding a publisher-specific DOCX layout.

## Observed result

The JATS import completed through the normal ContextWeaver path:

```text
contextweaver init PROJECT --source-language en --target-language zh-CN
contextweaver import PROJECT journal.pone.0251194.xml
contextweaver segment PROJECT --unit-size 2
contextweaver analyze PROJECT --adapter heuristic
contextweaver summarize PROJECT --adapter heuristic
contextweaver academic-assets PROJECT
contextweaver academic-pdf PROJECT --content source
```

The run produced 27 Sections, 68 stable Segments, and 44 TranslationUnits. Its import report recorded 55 body/abstract paragraphs, 24 headings, 2 figures, 4 tables, 72 citations, and 29 references. Both figure binaries were fetched into the ignored project with SHA-256 records, then rendered in a reflowed A4 source PDF. The automatic strategy correctly classified the source as a scholarly research article and added rules to preserve citation keys, figure/table labels, equations, units, and statistical symbols.

## Deliberate boundary

The current JATS path retains figure and table captions as source-preserving review blocks, converts actual table cells to Markdown tables, and fetches JATS figure resources only for PLOS ONE. The PDF renderer does not yet generate a journal-template facsimile, support all JATS asset providers, translate embedded bitmap labels, or export DOCX. Those are explicit requirements for the next academic publishing phase, rather than silent losses.

Source and license: [PLOS ONE article page](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0251194).
