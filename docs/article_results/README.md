# Article Results Materials

This directory is generated from the already-calculated artifacts in
`analysis-results/static-analysis/` and `outputs/`. It does not rerun LLM
generation, modify source outputs, or overwrite `comparison_outputs/`.

## Article assets

- `Results.tex` is the English Results section.
- `Supplementary_Tables.tex` includes the five supplementary LaTeX tables.
- `tables/` contains main-text and supplementary LaTeX tables.
- `figures/` contains 300-DPI PNG figures.
- `data/` preserves the row-level calculated CSV exports used by the section.
- `results_manifest.json` records scope and interpretation constraints.

Use `\usepackage{booktabs}` and `\usepackage{graphicx}` in the article
preamble. The paths in `Results.tex` assume compilation from the repository
root; adjust them if the article is elsewhere.

## Important scope limitations

This bundle reports direct-generation outputs only. Each condition has one
run, so within-condition stability is not estimable. It does not include
human-evaluation data.

## Current-artifact reconciliation

The article calculation performs a documented in-memory reconciliation for a
small number of successful metadata rows whose canonical CSV filename is
absent. A replacement is accepted only if the same condition directory
contains exactly one CSV artifact. `data/reconciliation_log.csv` records each
such selection. This rule does not change `outputs/`, its metadata, or the
older `comparison_outputs/` reports.

## Regeneration

```powershell
.\.venv\Scripts\python.exe scripts\generate_article_results.py
```
