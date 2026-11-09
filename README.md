# Evidence-Grounded Question Answering for Financial AI Governance

**City University of Hong Kong · CS5481 Data Engineering group project**

A retrieval-augmented generation (RAG) system over five official financial AI governance PDFs. The project connects page-preserving data engineering, semantic retrieval and grounded English question answering through a Streamlit interface. Answers carry exact source quotations and citations to physical PDF pages; insufficient evidence permits refusal. Recorded retrieval measurements, historical DeepSeek evaluations and the single GPT-6 Luna integration acceptance are separate evidence sets.

The reviewed V4 source was integrated through PR #7 into main at `8e5a568dfaf5d1702c2aa7f86f1a583ede6f4920`. V4 is a separate operator-bound acceptance controller, not the default application profile or a public live-run service. This README update does not activate it or authorize provider requests.

## Features and architecture

- Deterministic PDF extraction, two cleaning arms and four token-window configurations, with stable chunk IDs and one-based physical pages.
- Pinned MiniLM embeddings and persistent Chroma cosine collections, checked for compatible model, strategy and dataset metadata.
- Baseline Top-5 retrieval and an opt-in `joint_pairs8` path that supplies eight original evidence chunks.
- One-stage baseline QA or two-stage coverage planning followed by answer generation, with JSON/schema and quotation validation.
- Streamlit answer/source cards, explicit refusal and service-error states, and downloadable QA records.
- Frozen experimental inputs, recorded results and synthetic regression tests; private credentials, model caches and databases remain outside Git.

```text
Five official PDFs + checksum manifest
  -> PyMuPDF extraction by physical page
  -> baseline / enhanced cleaning with audit records
  -> token windows: 150 or 220 tokens, overlap 0 or 30
  -> pinned MiniLM: normalized 384-D embeddings
  -> persistent Chroma cosine collections + provenance/temporal metadata

English question -> query embedding -> retrieval
  -> baseline: Top-5 -> one-stage grounded generation
  -> joint_pairs8: eight chunks -> coverage plan
       -> unsupported question part: whole-question refusal
       -> supported plan: separate answer-generation request
  -> validate JSON, evidence IDs and exact quotations
  -> derive trusted PDF page citations -> Streamlit answer/source display
```

A real quotation establishes source membership, not that it supports every part of a claim. Claim completeness, qualifications and conflicting versions still require semantic review. The V4 controller adds its own durable two-dispatch guard around the two-stage path; it does not replace the normal Streamlit routing.

## Dataset

The checksum-pinned pilot contains **five official English-language documents and 165 physical PDF pages**:

| Issuer | Document | Date | Physical pages |
| --- | --- | --- | ---: |
| HKMA | High-level Principles on Artificial Intelligence | 2019-11-01 | 4 |
| HKMA | Annex A: Supervisory Guidance for Responsible Adoption of Artificial Intelligence | 2026-10-15 | 8 |
| FSB | The Financial Stability Implications of Artificial Intelligence | 2024-11-14 | 40 |
| FSB | Sound Practices for Responsible Adoption of Artificial Intelligence (AI): Final report | 2026-10-15 | 75 |
| BIS/FSI | Regulating AI in the financial sector: recent developments and main challenges | 2024-12-12 | 38 |

This mixes supervisory documents, non-binding reports and policy research; it is not five binding regulations. The 2019 HKMA circular is retained as a historical, superseded source. Publication date alone does not establish current applicability. Original filenames, direct source URLs, stable IDs and expected hashes are recorded in [the manifest](data/sources.csv), [acquisition metadata](data/catalog/pilot_sources.json) and [dataset catalog](docs/dataset_catalog.md). The course brief is project context, not a corpus document. PDFs, generated corpora, model weights and indexes must be prepared separately and are not bundled in Git.

## Data engineering and retrieval

PyMuPDF extracts each physical page independently. Baseline cleaning normalizes Unicode/whitespace; the enhanced arm conservatively removes repeated margins and logs removals. Token windows never combine pages, and each exported substring is re-tokenized without special tokens to verify its budget. The encoder/tokenizer is `sentence-transformers/all-MiniLM-L6-v2`, revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`; embeddings are normalized 384-dimensional vectors. Chroma stores original text and citation/temporal metadata in separate strategy/cleaning collections. See [chunking design](docs/chunking_experiment.md), [engineering benchmark](docs/benchmark_phase26.md) and [temporal metadata](docs/temporal_metadata.md).

The baseline retrieval API returns chunks ranked by increasing cosine distance, which is proximity rather than an answer-confidence probability. The eight-way comparison crosses two cleaning arms with 150/220-token windows and 0/30 overlap. The later `joint_pairs8` candidate preserves the first five chunks of its `closure8` proposal and jointly selects the final three, including existing continuation pairs. It selects original chunks rather than rewriting evidence. See [retrieval evaluation](docs/retrieval_evaluation.md) and [joint_pairs8 results and offline replay](experiments/joint_pairs8/README.md).

## Grounded generation and recorded evaluations

The two-stage workflow first proposes coverage for each question part using supplied source units. Missing coverage produces a whole-question refusal; an accepted plan permits a separate English answer-generation call. The original validator rejects malformed JSON, invalid evidence IDs, model-supplied links and quotations absent from the cited chunks. Page URLs and document/version information come from trusted metadata. API/retrieval failures remain service errors, not successful refusals. Planning is fallible and quotation matching does not establish entailment. See [the QA and application guide](docs/member_c_handoff.md).

| Evidence family | Configuration and denominator | Recorded observation | Interpretation |
| --- | --- | --- | --- |
| Retrieval benchmark | 24 gold questions, eight cleaning/window configurations, Top-5 page locators | At 150 tokens, overlap raises Hit@5 from 11/24 to 15/24 in both arms; enhanced 150/30 MRR@5 = 0.4722 and all-locators@5 = 13/24 | Page-level retrieval, not answer correctness; one warmed sequential pass |
| Historical official DeepSeek QA | `deepseek-flash`, enhanced 150/0 Top-5, 24 gold + 5 OOD questions | Draft grades: 8 correct, 3 partial, 13 incorrect; strict 8/24 = 33.33%; OOD refusal 5/5 | Codex source-reviewed draft judgments; independent human confirmation pending |
| Historical 40-question development regression | DeepSeek; 30 answerable + 10 expected-refusal items | Original complete40: 27/30 core, 24/30 all-claims support, 7/10 refusals; earlier planned full40: 27/30, 25/30, 10/10; later joint_pairs8: 29/30, 28/30, 10/10 | Exposed development set, not held-out accuracy or an equal-cost causal comparison |
| GPT-6 Luna V4 acceptance | One fresh frozen EXP11 planning/generation sequence | HTTP 200/200; two dispatches, zero retries; 10,702 reported tokens; 5.238 s after initialization; FSB physical page 6 citation | One integration case, not a GPT-6 Luna evaluation score or average latency |

Sources: [retrieval records](docs/retrieval_results.json), [official DeepSeek analysis](docs/answer_evaluation_official_analysis.md), [earlier full40 report](docs/experiments/generative40/report.md), [joint_pairs8 review](experiments/joint_pairs8/full40_review.json), [joint run audit](experiments/joint_pairs8/full40_run_audit.json), and [V4 source/evidence guide](docs/ofox_v4_source_reproduction.md). The historical school-gateway attempt and six-question demo records are separate from the completed official-provider QA evaluation. Gold-answer refusals remain misses in the answerable denominator. Historical B-review status fields are recorded provenance, not new human sign-off; B/C metric and answer review must not be assumed complete.

### V4 and historical acceptance safeguards

The successful V4 acceptance requested `openai/gpt-6-luna` via OfoxAI `POST https://api.ofox.ai/v1/chat/completions`, with configured route `azure_foundry`, JSON-object output, `reasoning_effort=low`, `max_completion_tokens=1200`, a 120-second request limit, zero retries and no fallback. Fresh planning and answer generation each returned HTTP 200. The exact quotation points to the FSB 2024 report, physical PDF page 6 (printed page 2). The registry stopped after the complete outcome. The configured route and returned model do not independently attest the provider's internal backend.

The historical `ofox_joint_pairs8` Streamlit profile selects the legacy six-attempt design described in [the original acceptance plan](docs/live_demo_acceptance_plan.md). The separately reviewed `rag_app.ofox_v4` controller permits at most **two durable dispatch reservations** for one exact EXP11 case, requires an accepted current-session plan before generation, and stops on completion or failure. It does not become active through the Streamlit profile or a new clone.

V4 requires the original private incident bindings and explicit source/session/path-bound authorization. Its stopped session must not be reset, resumed or provisioned again. Do not publish private approvals/registries, fabricate prerequisite state, bypass safeguards, or execute historical launchers for reproduction. The [V4 reproduction guide](docs/ofox_v4_source_reproduction.md) documents offline tests and the security boundary. A recorded classroom demonstration must be labelled as recorded; Streamlit has no supported recorded-result loader. No new live V4 run is offered here. Actual billing remains unverified: USD 0.50 was accepted financial tolerance, not a guaranteed cap, including cache-write uncertainty.

## Streamlit application

After the environment and local data are prepared below, copy the blank configuration template **only if no local `.env` exists**:

```bash
cp -n .env.example .env
# Edit .env locally; never put a provider key in a shell command, log or commit.
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open `http://localhost:8501`. Starting the page does not submit a model request; pressing **Submit** with a configured provider can make paid requests. Use only separately authorized credentials and execution scope. Inspect source quotations and physical page numbers, and restart Streamlit after changing configuration. Do not reset stopped acceptance registries to make another profile available.

| Profile | Actual supported behavior | Configuration |
| --- | --- | --- |
| `baseline` (default) | One-stage QA over enhanced `fixed_150`, Top-5 by default; at most one request per submission | `LLM_API_KEY`; example endpoint/model `https://api.deepseek.com` / `deepseek-flash` |
| `joint_pairs8` (opt-in) | Enhanced 150/30, eight original chunks, fresh evidence planning then generation; up to two requests per submission, 120 s and 1,200 output tokens per request | Set `RAG_DEMO_PROFILE=joint_pairs8` locally; requires the reviewed direct DeepSeek endpoint/model and a matching index/catalog copy |
| `ofox_joint_pairs8` (historical guarded acceptance) | Legacy controller, not V4; private fixed-registry consent checks apply | Not a generic demo/reproduction profile; do not provision or reuse stopped sessions |

The [blank template](.env.example) and [configuration class](src/rag_app/config.py) define `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_THINKING`, `LLM_JSON_MODE`, `RAG_TOP_K`, `RAG_COLLECTION`, `RAG_ARM`, `RAG_EXPERIMENT_DIR`, `RAG_MODEL_CACHE` and optional `RAG_MAX_DISTANCE`. The template sets a 60-second baseline timeout; the dataclass default is 30 seconds, and joint_pairs8 pins 120 seconds. Leave the distance cutoff blank unless independently calibrated. For gateways without DeepSeek's thinking parameter, use blank `LLM_THINKING`; baseline-compatible provider replacement does not change joint_pairs8's pinned provider policy. School virtual keys are not upstream vendor keys. More details: [QA/application configuration](docs/member_c_handoff.md#configuration-and-provider-replacement).

## Repository structure and documentation

```text
app.py                         Streamlit entry point
src/rag_ingest/                 extraction, cleaning, tokenization, embeddings and storage
src/rag_retrieval/              application-facing semantic retrieval
src/rag_app/                    configuration, QA, citations, demo profiles and guarded controllers
scripts/                       explicit data acquisition, audits and evaluation utilities
experiments/retrieval_candidates/ isolated retrieval candidates
experiments/generative40/       frozen two-stage runtime and historical evaluation
experiments/joint_pairs8/       locked eight-chunk candidate, snapshots and recorded results
data/catalog/                  checksums, provenance, temporal metadata and engineering records
data/evaluation/               24-question gold set and OOD questions
docs/                          A/B/C handoffs, evaluation reports and security/reproduction guides
requirements-*.txt             historical component locks and combined application lock
```

[Data quality](docs/data_quality_report.md) · [Data/storage handoff](docs/member_b_handoff.md) · [Retrieval/QA review](docs/retrieval_qa_review.md) · [QA/application handoff](docs/member_c_handoff.md) · [V4 offline reproduction](docs/ofox_v4_source_reproduction.md).

## Limitations and security

The five-document, English, text-extractable pilot is not a representative legal knowledge base. There is no OCR; page/column extraction, chunk boundaries and footnote continuation can lose useful context. A page hit, a real quote and a fully supported answer are different outcomes. The development sets were exposed during iteration, runs are small, and repeated-run/generalization claims are not established. Unknown temporal status is not current applicability. Independent human metric and claim review remains pending; no signatures or contribution percentages are inferred.

Keep actual `.env` files, keys, private authorization JSON/SQLite registries, provider/billing logs, caches, indexes and personal signatures outside Git. Source publication or running tests does not authorize paid requests. Use isolated copies for replay, never rewrite expected checksums to accept altered inputs, and preserve first responses and stopped state. Fresh dependency installation, current external download availability and cross-platform setup have not been re-certified by the recorded offline tests. The Windows notes include a historical newline workaround: current benchmark code explicitly writes LF JSONL, so do not apply the old CRLF conversion to this version. The platform-specific dependency caveat remains relevant.

The following setup commands are documented for separately authorized local reproduction. They were not executed as downloads, ingestion or evaluations for this README update.

## Installation

Use Python 3.11 (the validated environment) from the repository root. For the complete application and A/B/C tests, use the combined lock:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-app-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
```

The combined lock incorporates Streamlit's Pillow compatibility override; do not install the historical Phase 2 lock over this environment. See [application overrides](requirements-app-overrides.txt), [combined lock](requirements-app-lock.txt) and [project configuration](pyproject.toml). Preparing dependencies or missing assets requires authorized network access; a source checkout alone does not contain them. Existing validation reused prepared dependencies/cache rather than certifying a fresh install on every platform.

### Component-only installation alternatives

For the historical ingestion/tokenizer component alone, retain the original Phase 1 setup in a separate environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-build-isolation .
```

`requirements-lock.txt` pins the Phase 1 Python environment. `pyproject.toml` defines direct dependencies and optional `dev`, `phase2` and `app` groups. Alternatively, `python -m pip install '.[dev]'` resolves development dependencies afresh. Locks were validated on macOS arm64; OS-specific wheels and dependency caveats need checking on other platforms.

For Phase 1 alone, only tokenizer assets are needed. Prepare the cache once (network required; no model weights or PDFs are downloaded):

```bash
python -c 'from rag_ingest.chunking import load_tokenizer; from rag_ingest.cli import TOKENIZER_REVISION; load_tokenizer(TOKENIZER_REVISION, ".cache/huggingface/hub")'
```

The tokenizer is `sentence-transformers/all-MiniLM-L6-v2` at immutable revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. Absence of PyTorch may produce a Transformers notice; Phase 1 uses only the tokenizer.

## First team checkout: reproduce the existing five-document pilot

Git does not include the PDFs, processed JSONL, databases, environments or model cache. On a new checkout, run these commands **in this order** from the repository root. Use the combined application lock here; if it is already installed, skip the first three setup commands. Acquisition uses only the existing five catalog entries, with pinned SHA-256 checks; it does not expand the dataset. Network access is needed for dependencies, the five official PDFs and initial model preparation. If an official file changes or access is denied, stop and inspect the source rather than changing the pinned checksum.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-app-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/python scripts/download_pilot.py
.venv/bin/rag-store --prepare-model --allow-download --cache-dir .cache/huggingface/hub
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-ingest --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-store --input data/processed/fixed_150.jsonl data/processed/fixed_220_overlap_30.jsonl --db-dir data/chroma --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-benchmark --output-dir data/experiments/phase26_reproduction --catalog data/catalog/temporal_metadata.json --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Use a new benchmark output directory if it already exists. The original two-strategy pilot counts are 753 and 588. The four benchmark counts are baseline 753, 885, 536 and 588, and enhanced 749, 874, 534 and 584, in 150/0, 150/30, 220/0 and 220/30 order. Compare the benchmark's input checksums/configuration and structural counts; timings and file allocation need not match. The lock was validated on Python 3.11/macOS arm64; other platforms have not been validated. The alternative dependency-resolution command is documented below.

After this sequence, use `data/chroma` for the original pilot or `data/experiments/phase26_reproduction/<baseline|enhanced>/chroma` for the controlled experiment. Member B's access example uses the latter path. The original local measurement directory `phase26_run4` is not shipped through Git.

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

For provider/authorization regressions, use the [network-denied test bootstrap](docs/ofox_v4_source_reproduction.md#offline-tests-without-provider-access) with synthetic credentials and temporary stores. Do not load a real `.env` or use stopped registries in tests. The commands below require the prepared offline tokenizer/model assets.

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

Phase 2 is an optional component-only dependency group. The commands below extend a Phase 1 environment; do not apply its historical lock over the combined application environment:

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

For the application-facing `retrieve()` API, Windows reproduction, QA review, and the eight-way retrieval experiment, see [Member B retrieval and evaluation](docs/retrieval_evaluation.md).

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

Use `fixed_220_overlap_30` to open the other collection. `get` returns flat record lists; `query` returns lists grouped by query, including chunk IDs. Cosine distances are smaller for closer vectors. This example is the low-level storage/query interface; the application-facing retriever and joint_pairs8 selection are documented above. Query text exceeding MiniLM's input limit is rejected, so Member B must decide how to handle long queries. Reuse the same encoder instance for subsequent queries.

For Member C, each hit's ID and metadata identify the source PDF, URL, and one-based physical page. Printed PDF page labels may differ. Chunk text feeds the grounded QA service and its source display; those modules remain separate from ingestion/storage.

## Phase 2 verification and limits

Run all existing and new tests:

```bash
.venv/bin/python -m pytest -q
```

The default suite uses deterministic synthetic 384-dimensional embeddings with an explicitly different model identity, and real temporary Chroma PersistentClient databases. Mock encoders therefore cannot be mixed with production MiniLM collections. Tests check dimensions/normalization, batching and one-time model loading, metadata, cross-process persistence, repeated ingestion, isolation, nearest-neighbor smoke queries, configuration mismatches, malformed/empty inputs, explicit rebuild, and CLI statistics. Phase 1 tests still use the real cached tokenizer. Model API tests mock the SentenceTransformer constructor and do not require model weights or network. An additional real-model integration test is skipped by default. After preparing the full model cache at `.cache/huggingface/hub`, run all tests including that integration check with:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

The real-model test runs synthetic PDFs through Phase 1, embeds their chunks with cached MiniLM, stores both collections, checks 384-dimensional unit vectors and citation metadata, and performs a self-match query. Historical Phase 2 validation passed 59 tests with this test enabled; that is a component-stage count, not the current whole-project count. This is a synthetic integration check, not a real-corpus quality evaluation.

The five-document real-PDF pilot has been processed and audited (see `docs/data_quality_report.md`). Engineering smoke queries establish integration and traceability only; retrieval and answer measurements are reported separately above. The input validator currently holds the JSONL records in memory to complete validation before changing collections; vector generation and upserts are batched. The ingestion/storage layer has no concurrent-write coordination, transaction across batches/collections, OCR, automatic corpus-version management or automatic stale-record deletion. Retrieval and QA live in the separate group modules described above.

API references: [SentenceTransformer](https://sbert.net/docs/package_reference/sentence_transformer/model.html), [Chroma collection configuration](https://cookbook.chromadb.dev/core/configuration/), [Chroma collections](https://cookbook.chromadb.dev/core/collections/).

## Phase 2.5 pilot

The pilot is capped at five documents. Use `.venv/bin/python scripts/download_pilot.py` to explicitly acquire/reverify the catalogued sources and `.venv/bin/python scripts/audit_pilot.py` after running the existing ingestion/storage CLIs to regenerate the quality and smoke records. The audit downloads nothing and does not write vector records. See the linked catalog and quality report for provenance, limitations, measured results, and exact reproduction commands. Do not expand the dataset without a new user request.

## Phase 2.6 quality and controlled benchmarking

The default ingestion/storage behavior and pilot database are preserved. Optional modules add conservative margin cleaning, diagnostic quality flags, four size/overlap combinations, and a separate temporal catalog. The engineering benchmark does not expand the dataset or score retrieval relevance; the separate retrieval evaluation uses its outputs.

After installing the existing Phase 2 environment, reinstall the project to register the new CLI:

```bash
.venv/bin/python -m pip install --no-build-isolation --no-deps .
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/rag-benchmark --output-dir data/experiments/phase26_reproduction --catalog data/catalog/temporal_metadata.json --cache-dir .cache/huggingface/hub --batch-size 32
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Choose a new output directory each time. The benchmark checks PDF checksums, archives the original two JSONLs, recreates byte-identical baseline outputs, and creates baseline/enhanced databases with all four strategies in separate directories. Each collection is ingested twice and every record's identity, text, citation/temporal metadata, vector dimension/norm and repeat snapshot is verified. It never writes `data/raw`, `data/processed`, or `data/chroma`. It emits `benchmark.json`, `benchmark.md`, page/chunk JSONL, contexts, and full per-page cleaning audits.

The two new strategy names are `fixed_150_overlap_30` and `fixed_220`. They are accepted by `load_chunks` and `rag-store`; the original defaults and filenames remain unchanged. The benchmark is the optional CLI for producing all four configurations. Query-time algorithms live in the retrieval modules and isolated experiments described above.

The CSV and Chunk schemas are unchanged. Use `load_temporal_catalog` for a sidecar join on document_id, or `rag-store --catalog data/catalog/temporal_metadata.json --dataset-version <version> ...` to include scalar temporal fields in a **separate** database. The benchmark records stronger context automatically; avoid writing enhanced chunks into baseline collections. Known-status assertions require official evidence, and unknown status is not treated as current.

See [quality report](docs/data_quality_report.md), [chunking design](docs/chunking_experiment.md), [temporal schema](docs/temporal_metadata.md), [benchmark](docs/benchmark_phase26.md), and [Member B handoff](docs/member_b_handoff.md). The Phase 2.5 report is preserved in `docs/data_quality_report_phase25.md`.
