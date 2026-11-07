# Preserved source_neighbor8 retrieval candidate

These seven modules preserve the dependency chain used to build the frozen
`source_neighbor8` evidence snapshots: `BudgetRetriever` → sentence-boundary,
relation/source routing, passage reranking and the offline corpus retriever. They
are isolated experiment code and are not imported by the default application.

Use the already reproduced enhanced `fixed_150_overlap_30` collection and cached
pinned MiniLM model. For a live offline inspection, add this directory to
`PYTHONPATH`, import `BudgetRetriever`, instantiate with explicit
`experiment_dir`/`cache_dir` and `mode="source_neighbor8"`, and call
`retrieve(question, top_k=8, collection="fixed_150_overlap_30", arm="enhanced")`.
No model API calls are required. The standalone `passage_rerank.py` and
`all_question_retrieval.py` CLI mains are archived exploratory tools, not supported
reproduction entry points: their historical development/holdout questions and
route files are not shipped, and `--gold` does not replace those missing inputs.
Do not reconstruct those inputs or infer results by running these mains. Their
importable retrieval classes remain available to the candidate dependency chain.
Use `../joint_pairs8/verify_replay.py` for the supported frozen forty-context
offline replay; do not treat these archived CLIs as the complete40 runner.

`test_budget_retrieval.py` checks all modes' fixed budgets, retention of the
original five chunks, caller configuration and unmodified text. It uses synthetic
retrieval fixtures, not fabricated corpus documents.

Known limitations are frozen: neighbors are seeded from the first three baseline
hits; later source candidates may miss sentence-tail completion. Title/reference
competition and cross-page/footnote continuity remain uncorrected. See the
[evidence diagnosis](../../docs/experiments/generative40/evidence_completeness.md).
Do not hardcode evaluation question IDs or oracle page numbers into a fix.
