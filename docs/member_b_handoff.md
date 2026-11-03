# Member B handoff: Phase 2.6

The five raw documents and original pilot collections remain unchanged. Original DB: `data/chroma`, with 753 records in `finance_fixed_150` and 588 in `finance_overlap_220`. Original chunk outputs remain under `data/processed`. Baseline Phase 2.5 metrics are archived in `docs/data_quality_report_phase25.md`.

The selected Phase 2.6 benchmark is under `data/experiments/phase26_run4`. Each of `baseline/chroma` and `enhanced/chroma` contains the four collections listed in [chunking experiment](chunking_experiment.md). The two arms share raw document checksums but differ in cleaning; never combine their records for a controlled contrast. Full dataset ID/checksums, model identity/revision, dependency versions, hardware, configurations, code hashes and timings are in [benchmark JSON](benchmark_phase26.json).

For a new checkout, first run the complete bootstrap sequence in [README](../README.md#first-team-checkout-reproduce-the-existing-five-document-pilot). The ignored PDFs, JSONL, DBs and model cache are absent from Git. It installs dependencies, obtains only the five catalogued PDFs, prepares the pinned model, generates baseline JSONL/DB and builds `phase26_reproduction`. Do not run the benchmark before generating the baseline JSONL files it archives.

The `phase26_run4` directory identifies the recorded local measurements; it is not included in a clone. Use the run directory you actually reproduced. The example below uses the README's `phase26_reproduction` directory.

Use existing public interfaces:

```python
import json
from pathlib import Path
from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.vector_store import open_collection
from rag_ingest.temporal import load_temporal_catalog

arm = Path('data/experiments/phase26_reproduction/enhanced')
context = json.loads((arm / 'collection_context.json').read_text())
encoder = MiniLMEncoder('.cache/huggingface/hub', offline=True)
collection = open_collection(arm / 'chroma', 'fixed_150_overlap_30', encoder.spec,
                             context=context)
records = collection.get(limit=5, include=['documents', 'metadatas'])
# Reuse encoder.encode(question_texts, batch_size=...) for explicit query vectors.
# Member B owns query selection, retrieval settings and evaluation algorithms.
catalog = load_temporal_catalog(Path('data/catalog/temporal_metadata.json'))
```

Retrieval metadata contains the six original citation/strategy fields and ten temporal document fields; document_id is the shared key. Chroma IDs are chunk IDs, documents hold text, and stored embeddings are normalized 384-dimensional MiniLM vectors. Full temporal evidence is in the sidecar, not flattened into arbitrary strings. See [temporal schema](temporal_metadata.md) for unknown-status handling.

Suggested evaluation controls:

- Freeze PDF checksums, cleaning arm, model revision, question/evidence labels, query preprocessing, top-k and retrieval settings.
- Compare the 2×2 strategies within an arm; assess cleaning as its own factor.
- Keep historical and unknown status visible in evidence labels; do not infer current applicability from similarity or document date.
- Include questions about short valid sections, cross-page passages, tables and historical/current conflicts.
- Treat fixed-window sentence/word splits, bibliography/contents noise and remaining page-number artifacts as known limits.
- Use dataset version, cleaning version, strategy and chunk ID together when logging or joining results.

There are no new relevance scores, retrieval-quality claims, formal evaluation algorithms, LLM answers, or UI modules. The benchmark checks engineering consistency and repeated ingestion only.

To reproduce the benchmark, install the documented environment, then run from the repository root:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-benchmark --output-dir data/experiments/phase26_reproduction --catalog data/catalog/temporal_metadata.json --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Use a new output directory for each run. The benchmark refuses to overwrite a run, never rebuilds the pilot DB, validates initial empty experiment collections and checks every stored record/vector against its JSONL input both before and after a second upsert. Normal `rag-store` ingestion remains nontransactional across batches. A new checkout must acquire the same five pinned documents as described above; no additional documents should be collected.
