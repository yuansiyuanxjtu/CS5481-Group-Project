# CS5481 RAG: Member A, Phases 1 and 2

A small Python pipeline for PDF ingestion, page-preserving token chunking, normalized MiniLM embeddings, and persistent Chroma storage. The initial local checkout had no files, commits, or GitHub remote; this implementation starts the project here. A five-document official-source pilot has been downloaded and processed locally; PDFs and generated stores remain ignored by Git. See [dataset catalog](docs/dataset_catalog.md) and [quality report](docs/data_quality_report.md). The attached course brief is project context, not part of the knowledge-base corpus.

## Install

Use Python 3.11 (the version validated here). From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-build-isolation .
```

`pyproject.toml` defines direct runtime dependencies and a `dev` extra. `requirements-lock.txt` pins the full tested Python 3.11 environment, including pytest and tokenizer dependencies. Alternatively, `python -m pip install '.[dev]'` resolves the transitive dependencies afresh. OS-specific wheels are resolved by pip; the lock was validated on macOS arm64.

For Phase 1 alone, only tokenizer assets are needed. Prepare the cache once (network required; no model weights or PDFs are downloaded):

```bash
python -c 'from rag_ingest.chunking import load_tokenizer; from rag_ingest.cli import TOKENIZER_REVISION; load_tokenizer(TOKENIZER_REVISION, ".cache/huggingface/hub")'
```

The tokenizer is `sentence-transformers/all-MiniLM-L6-v2` at immutable revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. Absence of PyTorch may produce a Transformers notice; Phase 1 uses only the tokenizer.

## Register actual PDFs

Place manually collected, public English-language PDFs in `data/raw/`. Fill `data/sources.csv` with this exact header:

```csv
document_id,source_file,source_url
```

Each row must contain your assigned stable document ID, the PDF path relative to `data/raw/`, and the actual HTTP(S) URL from which you obtained it. The manifest now contains the five verified pilot documents; acquisition metadata and checksums are in `data/catalog/pilot_sources.json`. Use CSV quoting for fields containing commas. URLs are preserved, not downloaded or checked for reachability. IDs allow letters, numbers, `_`, and `-`, starting with a letter or number. Duplicate IDs or PDF paths, missing files, invalid URLs, and paths outside the PDF directory are rejected. Keep document IDs stable when reordering the manifest. Keep the same PDF bytes and source metadata for reproducible runs.

## Run

```bash
source .venv/bin/activate
rag-ingest --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
```

Equivalent module command:

```bash
python -m rag_ingest --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
```

Omit `--offline` to permit downloading missing tokenizer assets. No PDFs are fetched. Paths are relative to the working directory. `--help` lists options. An empty manifest exits with a useful error before loading the tokenizer. An all-empty/scanned corpus produces empty JSONL files and a warning; OCR is outside Phase 1.

Outputs (replaced on a successful rerun):

- `data/processed/fixed_150.jsonl`: up to 150 content tokens, no overlap.
- `data/processed/fixed_220_overlap_30.jsonl`: up to 220 content tokens, 30-token overlap.

No special tokens count toward the budget. Both sizes leave space for MiniLM's special tokens within its 256-token embedding input limit. Final chunks and short pages may contain fewer tokens. Windows never cross pages. Overlap is measured on the original page's tokenizer offsets; a window beginning inside a WordPiece word may tokenize differently in isolation. The exact exported text is re-tokenized for `token_count`, and its end is shortened if needed to meet the budget. Text remains a substring of the cleaned page rather than decoded/lowercased tokenizer output.

## Architecture and handoff

```text
sources.csv + PDFs
  -> manifest.py: validate provenance and sort by document ID
  -> pdf.py: extract physical pages with PyMuPDF; clean conservatively
  -> chunking.py: two deterministic offset-based token windows per page
  -> pipeline.py: stream separate UTF-8 JSONL outputs
```

`models.py` defines immutable `Source`, `Page`, and `Chunk` contracts. `cli.py` wires the pipeline together. Python callers can use `load_manifest`, `load_pdf`, `chunk_page`, and `run_pipeline` directly. Each JSONL line contains exactly:

| Field | Contract |
| --- | --- |
| `chunk_id` | `{document_id}_p{page_number}_c{page_chunk_index}_{chunk_strategy}` |
| `document_id` | Stable ID from the manifest |
| `source_file` | PDF path as entered in the manifest |
| `source_url` | Actual provenance URL from the manifest |
| `page_number` | One-based physical PDF page, not printed page label |
| `text` | Cleaned page substring |
| `chunk_strategy` | `fixed_150` or `fixed_220_overlap_30` |
| `token_count` | Number of tokenizer tokens in exported text, excluding special tokens |

Chunk indices are one-based within each page. The strategy suffix makes IDs unique across both outputs. IDs are stable for identical inputs, configuration, and software versions; changed PDF text or cleaning can change chunk boundaries, so regenerate downstream stores after such changes.

Cleaning applies Unicode NFKC normalization, removes non-whitespace control/format characters, and collapses whitespace. It retains case, punctuation, headers, footers, and hyphens; no content-based deletion or guessed dehyphenation is performed. Empty pages remain represented by the extraction API and produce no chunks, preserving later page numbers. PDF reading order is PyMuPDF's sorted text order; complex columns/tables may need later review. Image-only pages need OCR.

The pipeline stages outputs before replacement so extraction errors do not overwrite existing JSONL. Each file replacement is atomic; replacing the pair is not a transaction. Run one writer per output directory. It holds one page and that page's token offsets at a time.

## Tests and local verification

After installation and the tokenizer cache preparation above:

```bash
.venv/bin/python -m pytest -q
```

After editing source files, reinstall with `python -m pip install --no-build-isolation .` to update the CLI. Tests import the current source directly.

Tests are offline and use the actual pinned MiniLM tokenizer, not mocked token counts. Missing cache files fail visibly. Synthetic PDFs are generated only in pytest temporary directories, with explicitly fictional `example.invalid` URLs. Tests cover extraction, blank-page numbering, cleaning, both sizes, overlap and full token coverage, WordPiece boundaries, metadata, deterministic IDs, multi-PDF JSONL, byte-identical reruns, manifest errors, and preserving outputs after parsing errors.

After adding your real PDFs and running the CLI, inspect output counts and verify that each stored page number matches the physical PDF page. A quick schema/count inspection:

```bash
python - <<'PY'
import json
from pathlib import Path
for path in sorted(Path('data/processed').glob('*.jsonl')):
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    print(path.name, len(rows), 'chunks')
    if rows:
        print(rows[0])
PY
```

## Phase 2 installation

Phase 2 is an optional dependency group so the existing Phase 1 installation remains lightweight. Install into the same virtual environment:

```bash
source .venv/bin/activate
python -m pip install -r requirements-phase2-lock.txt
python -m pip install --no-build-isolation '.[phase2]'
```

The Phase 2 lock contains the full tested Python 3.11/macOS arm64 environment, including PyTorch and Chroma's transitive dependencies. `requirements-lock.txt` remains the Phase 1 lock. Alternatively, install `python -m pip install '.[phase2,dev]'` to resolve transitive dependencies afresh. Direct Phase 2 dependencies are sentence-transformers 5.1.2 and ChromaDB 1.3.5. Reinstall the package after editing source to update installed CLI commands.

## Cache the full embedding model once

The Phase 1 tokenizer cache does **not** contain model weights. With network access, explicitly prepare the full pinned MiniLM model:

```bash
rag-store --prepare-model --allow-download --cache-dir .cache/huggingface/hub
```

Then verify the cache without permitting downloads:

```bash
rag-store --prepare-model --cache-dir .cache/huggingface/hub
```

`rag-store` defaults to offline loading (`local_files_only=True`); `--allow-download` is required to permit model downloads. Cache preparation does not touch a database. Use the same cache directory on subsequent runs. For a disconnected machine, copy the entire prepared cache, including snapshot files and referenced blobs. Missing model files cause a clear error with the preparation command. No dataset or PDFs are downloaded by Phase 2.

The same immutable model revision used by Phase 1's tokenizer is used for embeddings. One CPU SentenceTransformer instance is loaded per invocation and reused for all batches. Outputs are float32, L2 normalized, and checked for shape `(batch_size, 384)`, finite values, and unit norms. Inputs beyond 256 tokens including special tokens are rejected rather than silently truncated. CPU execution improves portability; exact floating-point bits can still vary across library versions and hardware.

## Complete pipeline commands

First add actual PDFs and manifest rows, then run:

```bash
source .venv/bin/activate
rag-ingest --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
rag-store --input data/processed/fixed_150.jsonl data/processed/fixed_220_overlap_30.jsonl --db-dir data/chroma --cache-dir .cache/huggingface/hub --batch-size 32
```

Equivalent Phase 2 module entry point: `python -m rag_ingest.store_cli` with the same arguments. Multiple JSONL files may be supplied. Strategy fields route rows to collections; filenames do not determine routing. Before model loading or writes, inputs are checked for the exact Phase 1 schema, nonempty strings, positive integer page/token counts, supported strategies and budgets, matching chunk IDs, HTTP(S) provenance URLs, and duplicate IDs across inputs. Empty files, blank lines, malformed records, and repeated IDs are errors. Citation metadata is never inferred. Validation checks token_count's type and budget; it does not recompute the declared count. The real encoder separately checks the actual model input length.

Rerunning upserts records by stable chunk ID and does not create duplicates. Existing IDs are updated, while absent IDs remain in the collection. To replace a strategy's complete dataset (including removing stale IDs), explicitly rebuild that collection:

```bash
rag-store --input data/processed/fixed_150.jsonl --db-dir data/chroma --cache-dir .cache/huggingface/hub --batch-size 32 --rebuild
```

This deletes/recreates only `finance_fixed_150`; the overlap collection and unrelated collections remain intact. `--rebuild` with both inputs replaces both. Do not use it with a partial dataset unless that subset is the intended replacement. All targeted existing collections are preflighted before mutation. Normal ingestion rejects incompatible collection configuration; explicit rebuild can replace it. Empty/malformed input cannot trigger deletion. Writes occur batch by batch, so runtime failures can leave partial changes, and rebuild is **not transactional**. Keep a backup before rebuilding important data and use one writer per database directory.

## Database structure and metrics

`chromadb.PersistentClient` stores data under the selected `--db-dir` (default `data/chroma`, ignored by Git). It persists automatically; no separate `persist()` call is needed.

| Strategy | Collection | Distance |
| --- | --- | --- |
| `fixed_150` | `finance_fixed_150` | cosine |
| `fixed_220_overlap_30` | `finance_overlap_220` | cosine |

Every record contains:

- Chroma `id`: Phase 1 `chunk_id`.
- Chroma `document`: chunk text.
- Chroma `embedding`: normalized 384-dimensional vector.
- Chroma `metadata`: `document_id`, `source_file`, `source_url`, `page_number`, `chunk_strategy`, and `token_count`.

Collection metadata records model name, immutable revision, dimension, normalization, encoder recipe/version, maximum sequence length, schema version, chunk strategy, and distance metric. Ingestion and `open_collection` compare these against the requested encoder and check Chroma's actual HNSW distance configuration and a persisted vector sample. Foreign/unmarked collections are rejected. Raw direct Chroma writes can bypass these checks; use the ingestion API to maintain the contract. A default embedding function is deliberately disabled, so downstream code must pass query vectors explicitly.

The CLI prints a JSON report from the actual run:

| Metric | Meaning |
| --- | --- |
| `processed_chunks` | Rows successfully embedded and upserted during this run, including updates |
| `embedding_seconds` | Time spent encoding and validating vector batches; excludes model loading |
| `insertion_seconds` | Time spent in Chroma upsert calls |
| `model_load_seconds` | Time loading the encoder, including any explicitly allowed download |
| `effective_batch_size` | Requested batch size capped by Chroma's current maximum |
| `collections` | Per-target collection processed count and record counts before/after |
| `storage_bytes` | Sum of logical file sizes under the whole DB directory at measurement time |

Storage includes SQLite/index files and any journals or unrelated collections in that directory; it is not a per-collection allocation or OS disk-block usage. Timings are operational measurements, not retrieval-quality or performance claims. Model caches are excluded from DB size. Redirect stdout to a JSON file if you want to retain a report.

## Member B integration

Import the public functions below from the installed package. Use the same storage path, pinned encoder, and strategy as ingestion. The wrapper opens an existing collection and verifies its embedding contract; it does not create collections. Example access and a simple query smoke check:

```python
from pathlib import Path
from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.vector_store import open_collection

encoder = MiniLMEncoder(cache_dir=".cache/huggingface/hub", offline=True)
collection = open_collection(Path("data/chroma"), "fixed_150", encoder.spec)
print(collection.count())

# Read citation metadata and text without generating embeddings.
records = collection.get(limit=5, include=["documents", "metadatas"])

# Member B can supply query vectors to Chroma's standard query interface.
query_vectors = encoder.encode(["How are banking AI model risks managed?"], batch_size=1)
if collection.count():
    result = collection.query(
        query_embeddings=query_vectors.tolist(),
        n_results=min(5, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
```

Use `fixed_220_overlap_30` to open the other collection. `get` returns flat record lists; `query` returns lists grouped by query, including chunk IDs. Cosine distances are smaller for closer vectors. No retrieval ranking/fusion algorithm or evaluation framework is added here. Member B owns those choices and retrieval-quality comparison. Query text exceeding MiniLM's input limit is rejected, so Member B must decide how to handle long queries. Reuse the same encoder instance for subsequent queries.

For Member C, each hit's ID and metadata identify the source PDF, URL, and one-based physical page. Printed PDF page labels may differ. Chunk text remains available for grounded generation; no answer-generation or UI logic is included.

## Phase 2 verification and limits

Run all existing and new tests:

```bash
.venv/bin/python -m pytest -q
```

The default suite uses deterministic synthetic 384-dimensional embeddings with an explicitly different model identity, and real temporary Chroma PersistentClient databases. Mock encoders therefore cannot be mixed with production MiniLM collections. Tests check dimensions/normalization, batching and one-time model loading, metadata, cross-process persistence, repeated ingestion, isolation, nearest-neighbor smoke queries, configuration mismatches, malformed/empty inputs, explicit rebuild, and CLI statistics. Phase 1 tests still use the real cached tokenizer. Model API tests mock the SentenceTransformer constructor and do not require model weights or network. An additional real-model integration test is skipped by default. After preparing the full model cache at `.cache/huggingface/hub`, run all tests including that integration check with:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

The real-model test runs synthetic PDFs through Phase 1, embeds their chunks with cached MiniLM, stores both collections, checks 384-dimensional unit vectors and citation metadata, and performs a self-match query. Validation during development passed all 59 tests with this test enabled. This is a synthetic integration check, not a real-corpus quality evaluation.

The five-document real-PDF pilot has been processed and audited (see `docs/data_quality_report.md`). Smoke queries establish integration and traceability only; no retrieval accuracy or answer correctness is claimed. The input validator currently holds the JSONL records in memory to complete validation before changing collections; vector generation and upserts are batched. No concurrent-write coordination, transaction across batches/collections, OCR, corpus version tracking, automatic stale-record deletion, or retrieval evaluation is implemented. Phase 3 has not been started.

API references: [SentenceTransformer](https://sbert.net/docs/package_reference/sentence_transformer/model.html), [Chroma collection configuration](https://cookbook.chromadb.dev/core/configuration/), [Chroma collections](https://cookbook.chromadb.dev/core/collections/).

## Phase 2.5 pilot

The pilot is capped at five documents. Use `.venv/bin/python scripts/download_pilot.py` to explicitly acquire/reverify the catalogued sources and `.venv/bin/python scripts/audit_pilot.py` after running the existing ingestion/storage CLIs to regenerate the quality and smoke records. The audit downloads nothing and does not write vector records. See the linked catalog and quality report for provenance, limitations, measured results, and exact reproduction commands. Do not expand the dataset without a new user request.
