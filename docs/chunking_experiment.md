# Controlled chunking experiment: Phase 2.6

The original comparison changes both size and overlap, so it cannot isolate either factor. The optional benchmark now generates a 2×2 design:

| Size | Overlap | Strategy name | Chroma collection |
| ---: | ---: | --- | --- |
| 150 | 0 | `fixed_150` | `finance_fixed_150` |
| 150 | 30 | `fixed_150_overlap_30` | `finance_fixed_150_overlap_30` |
| 220 | 0 | `fixed_220` | `finance_fixed_220` |
| 220 | 30 | `fixed_220_overlap_30` | `finance_overlap_220` |

`STRATEGIES`, the default `rag-ingest` command, the existing JSONL filenames, and the default `COLLECTIONS` mapping still contain the original two configurations. `EXPERIMENT_STRATEGIES` and `ALL_COLLECTIONS` expose all four. The JSONL loader and `rag-store` accept the two additional strategy names. `chunk_page(page, tokenizer, strategy)` remains the shared chunking implementation.

The benchmark independently runs the four configurations on baseline text and enhanced text. Compare overlap at fixed size, then size at fixed overlap, **within one cleaning arm**. A baseline/enhanced contrast is a separate preprocessing experiment. Do not attribute preprocessing changes to chunk size or overlap.

All runs use the same five PDF checksums, one-based page boundaries, original token-window algorithm, pinned MiniLM tokenizer/model revision, CPU encoder, normalized 384-dimensional vectors, cosine metric, and batch size 32. Token counts exclude special tokens; every exported text is also checked including special tokens against MiniLM's 256-token effective input limit. Overlap is measured on original page token offsets, with the existing exported-text budget check retained.

Fixed windows still split words and sentences. This phase does not introduce a sentence-aware algorithm: changing boundary selection at the same time would confound the intended size/overlap comparison. This remains a possible later experiment.

The original `data/processed` outputs and `data/chroma` are unchanged. Each benchmark arm has a separate database and its own four collections. Chunk IDs remain deterministic, but the same ID can describe different text across cleaning versions. Use `(dataset_version, cleaning_version, strategy, chunk_id)` as the experiment identity; never merge databases merely because chunk IDs match.

Measured counts/distributions, invalid flags, timings, environment and record-consistency checks are in [benchmark report](benchmark_phase26.md) and [JSON](benchmark_phase26.json). Counts and runtimes are engineering measurements, not evidence of better retrieval. Member B must use identical question/evidence labels, retrieval configuration and evaluation procedures before comparing quality.
