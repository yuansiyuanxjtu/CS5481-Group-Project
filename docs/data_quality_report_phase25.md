# Pilot data quality and integration report

Measured at `2026-11-02T14:28:54.125479+00:00`. Results apply only to these five downloaded PDFs and this local CPU run. They are not retrieval accuracy, answer correctness, or general performance estimates.

## Corpus measurements

| Metric | Measured value |
| --- | ---: |
| Downloaded documents | 5 |
| Successfully parsed documents | 5 |
| Physical PDF pages | 165 |
| PDF file bytes | 2,904,620 |
| Raw extracted characters | 531,371 |
| Cleaned characters | 501,394 |
| Page text tokens (MiniLM; no special tokens) | 100,464 |
| Empty cleaned pages | 0 |
| Pages with 1–99 cleaned characters | 3 |
| Exact duplicate PDF files | 0 |
| Exact duplicate cleaned documents | 0 |

| Document ID | Pages | Cleaned characters | Page tokens | Fixed 150 chunks | Overlap 220 chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bis_20241212_ai_regulation` | 38 | 140,877 | 29,287 | 212 | 166 |
| `fsb_20241114_ai_stability` | 40 | 118,838 | 24,534 | 188 | 147 |
| `fsb_20261015_responsible_ai` | 75 | 214,837 | 41,417 | 314 | 243 |
| `hkma_20191101_ai_principles` | 4 | 7,887 | 1,436 | 11 | 10 |
| `hkma_20261015_ai_guidance` | 8 | 18,955 | 3,790 | 28 | 22 |

Counts refer to one-based physical pages and the existing cleaning function. No parser failures were caught and reclassified as successes. No image-only document was identified; every page has some extracted text, although this does not prove every diagram or embedded image was captured.

Low-text pages were inspected: FSB 2024 page 1 is an 80-character cover; FSB 2024 page 4 and FSB 2026 page 4 contain only the roman page label `iv` (two characters, one token). These pages are retained by the unchanged pipeline, producing low-information chunks. They are not extraction failures. All extracted replacement-character counts (`U+FFFD`) were zero.

## Chunk and database measurements

| Strategy | Chunks / DB records | Mean tokens | Mean characters | Token range |
| --- | ---: | ---: | ---: | --- |
| `fixed_150` | 753 | 133.44 | 665.31 | 1–150 |
| `fixed_220_overlap_30` | 588 | 192.45 | 958.65 | 1–220 |

- Initial run: 1,341 processed chunks, batch size 32; both collections had zero records before insertion.
- Embedding generation and validation: **11.487 seconds**; Chroma upsert calls: **1.396 seconds**.
- Model load: **3.609 seconds**, using the already cached pinned MiniLM model offline.
- `finance_fixed_150`: **753** records; `finance_overlap_220`: **588** records.
- Database logical file size: **15,876,424 bytes** (15.14 MiB), including SQLite and index files; excludes model cache and PDFs.
- Every stored vector was checked for dimension 384 and unit norm. Every stored ID, text, and citation-metadata field was compared against its JSONL record. Every JSONL text was found on its stated cleaned physical page and re-tokenized to verify token_count.
- Page token totals exclude overlap. The sum of chunk token counts can differ because overlaps repeat text and window boundaries can change WordPiece tokenization.

## Representative review and extraction issues

Review covered 20 representative chunk records (first substantial page and middle chunk, for each document and strategy), all 1,341 records with automated traceability checks, and one rendered body page per PDF. The representative selection includes contents/disclaimer pages in the longer reports; those are explicitly part of the corpus. The rendered pages were HKMA 2019 p2, HKMA 2026 p3, FSB 2024 p5, FSB 2026 p7, and BIS p5. Full representative records are in `data/catalog/representative_chunks.json`.

| Document | Observed issue | Consequence |
| --- | --- | --- |
| HKMA 2019 | Physical page numbers such as `- 2 -` remain in text; fixed windows split sentences. | Some noise; page metadata is still correct. Historical status is not encoded in chunk metadata. |
| HKMA 2026 | Body paragraphs continue across pages and footnotes remain inline; overlapping chunks can end inside a word. | A single chunk may omit surrounding explanation even though its citation is traceable. |
| FSB 2024 | Contents dot leaders and page-label-only pages are indexed; tables flatten into prose and headings. | Low-information chunks and reduced table structure. Physical page 5 is printed page 1. |
| FSB 2026 | Contents, footnotes, references and page-label-only pages are indexed; some middle chunks contain mostly citations. | Retrieval may return navigation or bibliography rather than substantive guidance. Physical page 7 is printed page 3. |
| BIS/FSI | Repeated title footers; some sorted footer text contains duplicated phrase fragments; chart glyphs use private-use characters. | Cleaning removes private-use glyphs, and page-order flattening loses visual associations. Physical page 5 is printed page 2. |

The existing NFKC/whitespace cleaner was not changed. It removes 22 category-C private-use characters (U+F081–U+F087) from the BIS extraction; these are not U+FFFD replacement errors. A visual sample confirms clear body text but cannot certify all charts/tables across 165 pages. The BIS title footer was detected on 18 pages, and a variant prefixed with a duplicated phrase fragment on 17 pages, after stripping numeric page labels. The repeated footer phrase in the BIS extraction is an observed PDF extraction artifact, not newly generated text. No general header/footer removal is currently performed.

Heuristic boundary counts (first exact substring location on a page, not linguistic ground truth):

| Strategy | Mid-word starts | Mid-word ends | Non-sentence ends before page end |
| --- | ---: | ---: | ---: |
| `fixed_150` | 42 | 42 | 514 |
| `fixed_220_overlap_30` | 27 | 45 | 375 |

These are expected limitations of fixed token windows, not evidence of missing source pages. Sentence-end checks use punctuation only; repeated text can make the location heuristic ambiguous. Token budgets and exported token counts passed validation. Repeated edge-line diagnostics strip numeric page labels and identify exact recurring strings; they do not exhaustively detect all running headers or footers.

## Five-question smoke test

Each question was embedded with the cached model and queried against both collections, requesting two hits: **10 query/collection combinations and 20 retrieved hits**. Full hit text, IDs, cosine distances and source metadata were printed and saved to `data/catalog/smoke_results.json`. All 20 hits passed local source-file, URL, physical-page and text-substring trace checks. No LLM answers, relevance labels, hit rates, or accuracy claims were produced.

| Question topic | Fixed 150 top hit (physical page) | Overlap 220 top hit (physical page) |
| --- | --- | --- |
| What responsibilities do bank boards and senior management have for AI governance? | `bis_20241212_ai_regulation`, p32 | `hkma_20191101_ai_principles`, p2 |
| How should financial institutions ensure AI explainability and transparency? | `bis_20241212_ai_regulation`, p26 | `fsb_20261015_responsible_ai`, p42 |
| What data quality and data governance controls are needed for AI models? | `fsb_20261015_responsible_ai`, p39 | `hkma_20191101_ai_principles`, p2 |
| How can third-party AI providers create concentration and operational risks? | `fsb_20261015_responsible_ai`, p21 | `fsb_20261015_responsible_ai`, p66 |
| What human oversight and validation should banks apply to generative AI? | `hkma_20191101_ai_principles`, p2 | `hkma_20191101_ai_principles`, p2 |

The governance, data-quality, and human-oversight queries sometimes rank the superseded 2019 HKMA circular first or second. This demonstrates why traceability alone is insufficient to establish current applicability. Formal relevance judgments, temporal filtering, and chunking-quality comparisons remain Member B’s work. Before Member C generates answers, the team should agree how historical versus current guidance is represented or filtered.

## Reproduction commands

Install the Phase 2 environment using README instructions. The first command below makes at most five official PDF downloads and reuses checksum-matching local files. All remaining processing is offline:

```bash
.venv/bin/python scripts/download_pilot.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-ingest --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-store --input data/processed/fixed_150.jsonl data/processed/fixed_220_overlap_30.jsonl --db-dir data/chroma --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/audit_pilot.py
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Before ingestion, this run checked that `data/chroma` did not exist; no collections were destructively rebuilt. Reproduction uses normal upserts, not `--rebuild`. Timings and storage size may vary. The audit fails if database counts include stale/missing pilot records, so inspect an existing DB before reusing it. Initial ingestion timings are preserved in `data/catalog/phase2_metrics.json`; rerunning the audit refreshes quality and smoke JSON only.

## Regression checks

The offline full suite, including the real-model synthetic integration test, passed **59 tests** in **10.69 seconds**. PyMuPDF and Chroma emitted 37 dependency deprecation warnings; there were no failures. The exact pytest command is above, and output is saved in `data/catalog/test_run.txt`. The working Phase 1/2 source modules and APIs were not changed for this pilot.

## Next steps within team responsibilities

1. Stop collection at these five PDFs pending the user’s instruction; do not expand automatically.
2. Ask Member B to create formal question/answer evidence labels and compare the two collections; these smoke queries do not replace that evaluation.
3. Agree on handling superseded guidance before Member C uses it in answers. The catalog can be joined on document_id without changing current APIs.
4. Consider a later, explicitly versioned cleaning/chunking experiment for page-label-only pages, contents, running footers, sentence/word boundaries and table extraction. Retain baseline outputs for comparison.
5. Keep raw-file checksums and acquisition metadata with the report; verify source versions again before any later expansion.
