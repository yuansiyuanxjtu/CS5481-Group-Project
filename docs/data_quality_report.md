# Phase 2.6 data quality report

Finalized run: `data/experiments/phase26_run4`; completed `2026-11-03T01:54:45.887905+00:00`. Dataset `pilot5_8321c43ee6b1`. Phase 2.5 baseline report is preserved in [the archive](data_quality_report_phase25.md). Original raw PDFs, both original JSONL files and the complete pilot database were verified byte-identical after the work.

## Rules and preservation

The opt-in `conservative_margins_v1` profile retains the existing NFKC/control/whitespace normalization, then removes only geometry-confirmed margin page labels and manually approved BIS bottom-margin footer strings. Margin centers are within the outer 6% of page height. Numeric labels must not exceed the physical document length, protecting dates such as 2026. A sorted text line is removed only when it consists entirely of approved margin components; mixed body/margin lines and ambiguous repeated occurrences remain. Every removal has a page-level audit with before/after text and rule names.

Header/footer recurrence is measured over geometry-derived margin lines, with at least three distinct pages needed to report a repeated string. Recurrence alone does not authorize deletion. Only the reviewed BIS title footer and hidden duplicate phrase fragment are allowlisted, for that document ID. Document checksums are verified before the benchmark applies the profile. Other headers, footnotes, citations, tables, contents, legal notices and short valid sections are retained. No LLM rewriting, general deduplication, sentence rewriting or threshold-based dropping is performed.

The original APIs/default two strategies are preserved. Baseline and enhanced text use the same token-window algorithm. Enhanced outputs and databases are isolated under the benchmark run; the pilot outputs are not overwritten. All physical pages remain represented, even when cleaning produces empty text and no chunk.

## Measured before/after

| Metric | Baseline | Enhanced |
| --- | ---: | ---: |
| Successfully visited physical pages | 165 | 165 |
| Cleaned characters | 501,394 | 497,252 |
| Empty cleaned pages | 0 | 2 |
| Nonempty pages below 100 characters | 3 | 1 |
| Whole pages consisting only of a page label | 2 | 0 |
| Exact duplicate nonempty pages | 1 | 0 |
| Pages with logged removals | 0 | 155 |

The two newly empty pages are FSB 2024 physical page 4 and FSB 2026 physical page 4, previously containing only `iv`. These are logged label removals, not parsing failures. The FSB 2024 cover remains the one nonempty page below 100 characters. All five documents parsed, all 165 physical pages were visited, and no document was added or removed. These coverage counts do not establish completeness of figures or image text.

| Strategy | Baseline chunks | Enhanced chunks | Mean tokens before / after | Short chunks before / after | Duplicate texts before / after |
| --- | ---: | ---: | --- | --- | --- |
| `fixed_150` | 753 | 749 | 133.44 / 133.23 | 10 / 11 | 2 / 1 |
| `fixed_150_overlap_30` | 885 | 874 | 137.93 / 138.57 | 2 / 0 | 3 / 2 |
| `fixed_220` | 536 | 534 | 187.46 / 186.87 | 7 / 8 | 1 / 0 |
| `fixed_220_overlap_30` | 588 | 584 | 192.45 / 192.48 | 2 / 0 | 1 / 0 |

Short means fewer than 10 content tokens. It is a review flag, not a rejection rule: short valid clauses and footnote remainders remain. Consequently the number of short chunks can increase after re-chunking. Exact duplicate text counts are within each strategy, not cross-strategy, and exclude neither boilerplate nor legitimate repetition. They are reported without deletion.

For all eight arm/strategy combinations: **zero structurally invalid chunks, missing citation fields, source/page integrity failures, duplicate IDs, invalid token counts, model-limit violations or malformed-text flags**. All exported token counts were recomputed. Every model input, including special tokens, fit within 256 tokens. Every stored vector had dimension 384 and unit norm. Every stored ID/text/metadata record matched its JSONL input before and after repeat ingestion.

All enhanced strategies have zero chunks from a whole page that consists solely of a page label (baseline: two per strategy). The broader syntactic `page_label_candidates` detector also flags bare numeric/roman strings inside normal pages: one enhanced `fixed_220` chunk contains the meaningful footnote year `2026`. It is retained and is not classified as a confirmed page-label-only page. Do not use candidate counts as an automatic deletion rule.

## Before/after examples

- FSB 2024 p4 and FSB 2026 p4: before `iv`; after empty text. Their physical page identities and audit entries remain.
- BIS p5: the merged bottom line contains a page numeral, the repeated title footer and a duplicated hidden phrase. That whole geometry-confirmed margin line is removed; all body paragraphs remain. Rendered p5 confirms the visible body/footer positions. Full exact before/after page text and removed-line lists are in `enhanced/cleaning_audit.json`.
- HKMA 2026 p1: the bottom page numeral is removed, while the Purpose section, explicit supersession statement, footnotes and their publication years remain.
- HKMA 2019 p2: the `- 2 -` header is outside the deliberately narrow margin region; it remains. The governance principles and numeric requirements are unchanged.

## Remaining boundary and layout issues

| Strategy | Mid-word starts before / after | Mid-word ends before / after | Non-sentence ends before / after |
| --- | --- | --- | --- |
| `fixed_150` | 42 / 41 | 42 / 41 | 514 / 512 |
| `fixed_150_overlap_30` | 42 / 41 | 48 / 48 | 625 / 620 |
| `fixed_220` | 35 / 35 | 35 / 35 | 327 / 327 |
| `fixed_220_overlap_30` | 27 / 27 | 45 / 45 | 375 / 374 |

These are substring/punctuation heuristics, not linguistic judgments. Fixed windows still break sentences and WordPiece words; this was held constant for the controlled 2×2 experiment. Table structures flatten, body/footnote reading order remains imperfect, contents/references remain indexable, and the pre-existing normalization still removes category-C private-use glyphs. No OCR or semantic repair is claimed. Numeric-only or roman-looking body fragments can be legitimate. Near-duplicate content is not measured beyond exact matches.

## Benchmark and temporal results

Engineering measurements and the full machine-readable record are in [benchmark report](benchmark_phase26.md) and [JSON](benchmark_phase26.json). Each of the eight experiment collections was ingested twice with identical input and batch size; counts, text, metadata and vector snapshots remained identical. Timing samples are one measured finalized run, in fixed order, not a statistically controlled performance comparison. Three development runs remain in the ignored experiment directory; only run4 is reported here. Hardware details available to the process were macOS arm64, ten logical CPUs and Python 3.11.15. Model/RAM identifiers were unavailable through the sandbox and are recorded as unavailable rather than guessed.

All ten requested temporal fields are supplied separately and copied into experiment record metadata. Only the 2019 HKMA principles have an evidence-backed `superseded` status. Other statuses are `unknown`, not inferred current from their dates. See [temporal metadata](temporal_metadata.md) and [Member B handoff](member_b_handoff.md). No legal applicability or retrieval filter is implemented.

## Reproduction and tests

```bash
.venv/bin/python -m pip install --no-build-isolation --no-deps .
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-benchmark --output-dir data/experiments/phase26_reproduction --catalog data/catalog/temporal_metadata.json --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Use a new output directory. No downloads or destructive rebuilds are involved. The default original `rag-ingest` and `rag-store` commands remain valid. The benchmark archives and regenerates byte-identical original baseline JSONL, stores PDF and code checksums/configurations/environment, verifies full collection consistency, and logs every cleaning removal. Its generated benchmark JSON is the authoritative machine-readable measurement record.

The full suite passed **81 tests**, including the original 59, additional quality/temporal/configuration/benchmark checks, and the opt-in cached real-model integration test. Dependency deprecation warnings remain. Final test output is in `docs/phase26_test_results.txt`.

## Limits for Members B and C

Member B still needs to evaluate retrieval quality with identical labels/settings and compare size/overlap within each cleaning arm. More retained context or fewer footer tokens does not establish better retrieval. Member C must retain document/page/date provenance, surface superseded status, and treat unknown applicability conservatively. IDs can collide across cleaning arms, so include dataset/cleaning version in joins. Do not expand the dataset or proceed to Phase 3 without a new request.
