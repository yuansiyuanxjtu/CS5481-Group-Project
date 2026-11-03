# Phase 2.6 benchmark

Dataset: `pilot5_8321c43ee6b1`; five unchanged PDFs.

Single CPU run, fixed strategy order, no warm-up exclusion or statistical repetitions. First ingestion is an empty DB per arm; repeated ingestion re-encodes identical chunks. This measures data engineering, not retrieval quality.

| Arm | Strategy | Chunks | Mean tokens | Page-label chunks | Invalid | Encode s | Insert s | Repeat identical |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | fixed_150 | 753 | 133.44 | 2 | 0 | 2.887 | 0.541 | yes |
| baseline | fixed_150_overlap_30 | 885 | 137.93 | 2 | 0 | 3.403 | 0.748 | yes |
| baseline | fixed_220 | 536 | 187.46 | 2 | 0 | 3.238 | 0.441 | yes |
| baseline | fixed_220_overlap_30 | 588 | 192.45 | 2 | 0 | 3.540 | 0.575 | yes |
| enhanced | fixed_150 | 749 | 133.23 | 0 | 0 | 2.866 | 0.522 | yes |
| enhanced | fixed_150_overlap_30 | 874 | 138.57 | 0 | 0 | 3.344 | 0.733 | yes |
| enhanced | fixed_220 | 534 | 186.87 | 0 | 0 | 3.224 | 0.454 | yes |
| enhanced | fixed_220_overlap_30 | 584 | 192.48 | 0 | 0 | 3.530 | 0.587 | yes |

baseline: PDF processing 1.674s; 501,394 cleaned characters; DB 40,117,190 bytes.


enhanced: PDF processing 3.615s; 497,252 cleaned characters; DB 39,702,382 bytes.

Full distributions, environment/dependency details, raw-file checksums, code/config fingerprints, contexts and first/repeat timings are in `benchmark.json`. Cleaning audit logs preserve before/after page text and removed lines. The original two JSONL outputs are archived and verified byte-identical to recomputed baseline outputs. Original PDFs and the pilot DB were not written.

Collection sizes are logical file bytes for all four collections per arm, after repeat ingestion; SQLite journal/index allocation can vary. Extraction coverage means physical pages visited with successful extraction, not verified completeness of charts or OCR. Short/malformed/duplicate flags are diagnostics, distinct from structural invalidity. Sentence/word boundary counts are punctuation/substring heuristics, not linguistic accuracy measures.
