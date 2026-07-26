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
```

The run produced 27 Sections, 66 stable Segments, and 42 TranslationUnits. Its import report recorded 55 body/abstract paragraphs, 24 headings, 2 figures, 4 tables, 72 citations, and 29 references. The automatic strategy correctly classified the source as a scholarly research article and added rules to preserve citation keys, figure/table labels, equations, units, and statistical symbols.

## Deliberate boundary

The current JATS path retains figure and table captions as source-preserving review blocks, and converts actual table cells to Markdown tables. It does not yet fetch graphic binaries, generate Chinese figure labels, or render a publication-quality PDF/DOCX. Those are explicit requirements for the next academic publishing phase, rather than silent losses.

Source and license: [PLOS ONE article page](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0251194).
