# joint_pairs8 retrieval experiment

`joint_pairs8` keeps the first five evidence chunks and selects the final three together. It ranks passages inside the requested source or section, considers neighboring text for case studies, and keeps or removes existing continuation pairs as a unit. The experiment returns eight original chunks through an explicit entry point and lives separately from the default application.

## Complete 40-question first-response results

| Metric | Original baseline | Previous full40 | joint_pairs8 |
|---|---:|---:|---:|
| Strict core correctness | 27/30 (90.0%) | 27/30 (90.0%) | 29/30 (96.7%) |
| Complete answer with all claims supported by the selected quotes | 24/30 (80.0%) | 25/30 (83.3%) | 28/30 (93.3%) |
| Correct whole-question refusal | 7/10 | 10/10 | 10/10 |

The new candidate ran the same 40 questions in the same order, with the frozen two-stage prompts and the same provider model settings. All 69 requests returned HTTP 200. The run used 403,382 tokens and produced 40 first responses. The previous full40 serves as the comparison. [Run audit](full40_run_audit.json) · [B review of all 40 responses](full40_review.json)

- EXP29 and EXP30 recovered both required facts and their citations. EXP20 gained full quote support for its subcontractor-dependence claim.
- EXP28 still refused because the eight chunks lacked the relevant BIS passage. It remains a miss in the answerable denominator. EXP05 passed the core metric and retained a quote-scope gap for ongoing monitoring.
- Offline reference evidence coverage rose from 28/30 with `closure8` to 29/30 with `joint_pairs8`. The offline comparison changed four contexts, including one refusal question. [Coverage](offline_coverage.json) · [Per-question changes](offline_deltas40.json)

These are first-response results on an exposed regression set. The run records the returned provider model and fingerprint. More runs would be needed to measure sampling or service variability.

## Offline replay

Use the project's existing Python environment, a copy of the reproduced Phase 2.6 enhanced index, and the cached pinned MiniLM encoder. On Windows, use an ASCII path for the index copy if native HNSW loading fails on a non-ASCII path.

```text
python experiments/joint_pairs8/verify_replay.py --experiment-dir ISOLATED_INDEX_COPY --cache-dir OFFLINE_MODEL_CACHE
```

The replay checks the 40 frozen first-stage messages against their evidence inventory, and checks live chunk IDs, order, original text, source metadata and evidence numbers against the snapshots. Distance comparisons allow a small floating-point difference across machines. The replay uses the local encoder without requesting a generation model.

To use the experiment directly, put this directory and the project's `src` on the Python import path. Instantiate `candidate_entry.JointCandidateRetriever(experiment_dir, cache_dir)` and call `retrieve(question, top_k=8, collection='fixed_150_overlap_30', arm='enhanced')`. The entry checks its code and the reused baseline modules against the lock before opening the supplied index.

`model_inputs40.json` is the exact first-stage request snapshot used for the complete run. The [generation protocol](generation_protocol.json) binds the generation prompt in the existing [two-stage experiment](../generative40). The audit and scores are kept separately from model inputs. Raw provider responses and trial authorization records are held in the project archive.
