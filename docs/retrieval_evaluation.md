# Member B retrieval and evaluation

## Reproduce the pilot in Windows PowerShell

Run from the repository root with `uv` installed. The original Phase 2 lock includes `uvloop==0.23.0`, which fails to build on Windows. The generated local install list skips that package and retains every other pin. The tracked lock and Member A's APIs stay intact. UTF-8 mode also makes the original benchmark's catalog read independent of the Windows code page.

```powershell
$env:UV_CACHE_DIR = "$PWD/.cache/uv"
$env:UV_PYTHON_INSTALL_DIR = "$PWD/.cache/python"
$env:PYTHONUTF8 = '1'
$env:HF_HOME = "$PWD/.cache/huggingface"
$env:HF_HUB_DISABLE_XET = '1'
$env:TOKENIZERS_PARALLELISM = 'false'
uv python install 3.11.15
uv venv --python 3.11.15 .venv
$py = '.venv/Scripts/python.exe'
Get-Content requirements-phase2-lock.txt | Where-Object { $_ -notmatch '^uvloop==' } |
    Set-Content -Encoding ascii .cache/requirements-phase2-windows.txt
uv pip install --python $py -r .cache/requirements-phase2-windows.txt
uv pip install --python $py --no-build-isolation --no-deps .
uv pip check --python $py
& $py scripts/download_pilot.py
.venv/Scripts/rag-store.exe --prepare-model --allow-download --cache-dir .cache/huggingface/hub

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
.venv/Scripts/rag-ingest.exe --manifest data/sources.csv --pdf-dir data/raw --output-dir data/processed --cache-dir .cache/huggingface/hub --offline
.venv/Scripts/rag-store.exe --input data/processed/fixed_150.jsonl data/processed/fixed_220_overlap_30.jsonl --db-dir data/chroma --cache-dir .cache/huggingface/hub --batch-size 32

@'
from pathlib import Path

staging = Path('.cache/windows-benchmark-baseline')
staging.mkdir(exist_ok=True)
for name in ('fixed_150', 'fixed_220_overlap_30'):
    source = Path('data/processed') / f'{name}.jsonl'
    original = source.read_bytes()
    assert b'\r\n' not in original
    target = staging / source.name
    target.write_bytes(original.replace(b'\n', b'\r\n'))
    assert target.read_bytes().replace(b'\r\n', b'\n') == original
'@ | & $py -
.venv/Scripts/rag-benchmark.exe --baseline-dir .cache/windows-benchmark-baseline --output-dir data/experiments/phase26_reproduction --catalog data/catalog/temporal_metadata.json --cache-dir .cache/huggingface/hub --batch-size 32
```

On Windows, `rag-ingest` writes LF JSONL and `rag-benchmark` writes CRLF JSONL. The default benchmark command fails its byte-identical baseline check. The staged copies above change only newline bytes so the original benchmark can compare CRLF to CRLF. The original `data/processed` outputs remain byte-identical to A's tracked report. The corresponding A test reproduces the failure. For A to coordinate, the benchmark JSONL write in `src/rag_ingest/benchmark.py` can explicitly request `newline="\n"` to align with `run_pipeline`. The Windows dependency issue is separate and can be addressed with a platform marker on `uvloop` in a shared lock update.

`download_pilot.py` checks the pinned SHA-256 of each official PDF. It refreshes local acquisition metadata in the tracked pilot catalog, so review that diff before staging. The benchmark requires a fresh output directory. For subsequent runs, supply a new directory to both `rag-benchmark` and `scripts/eval_retrieval.py --experiment-dir`.

The 2026-11-03 run used Windows 11 25H2 build 26200 (x64), CPython 3.11.15, an Intel Core i7-12700H with 20 logical CPUs, and CPU-only model inference. All five official PDFs matched their pinned SHA-256 and contained 165 physical pages in total. The original pilot yielded 753 `fixed_150` chunks and 588 `fixed_220_overlap_30` chunks. MiniLM loaded from the pinned revision in offline mode for ingestion and retrieval. The Windows environment retained `PyMuPDF 1.26.6`, `ChromaDB 1.3.5`, `sentence-transformers 5.1.2`, `transformers 4.57.1` and `torch 2.15.0`.

## Member C integration

From the repository root after installation and reproduction:

```python
from rag_retrieval import retrieve

question = "Which earlier HKMA document did the October 2026 supervisory guidance explicitly supersede?"
evidence = retrieve(question, top_k=5, collection="fixed_150", arm="enhanced")
for hit in evidence:
    print(hit["chunk_id"], hit["document_id"], hit["source_url"], hit["page_number"])
    print(hit["distance"], hit["regulatory_status"], hit["text"])
```

For an alternate completed run, instantiate `rag_retrieval.Retriever(experiment_dir, cache_dir)` once and call its `retrieve()` with the same arguments. The caller receives up to `top_k` chunks ranked by increasing cosine distance, with one-based physical PDF pages and the stored `title`, `publication_date` and `regulatory_status`. A's statuses are passed through verbatim. For the official evidence behind a status, join the run's `temporal_catalog.json` by `document_id`. Low cosine distance measures proximity in embedding space. Member C should judge whether the returned text supports an answer and attach citations using the exact result fields.

The first request loads MiniLM and checks the collection. Reuse the same instance for subsequent requests. Blank questions, invalid `top_k`, and unknown arms or strategies raise `ValueError`. MiniLM also rejects queries beyond its 256-token input limit. Report missing or incompatible stores separately from questions with insufficient evidence.

## Run the evaluation and tests

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONUTF8 = '1'
$env:TOKENIZERS_PARALLELISM = 'false'
.venv/Scripts/python.exe scripts/eval_retrieval.py --torch-threads 4 --output docs/retrieval_results.json
$env:RAG_TEST_REAL_MODEL = '1'
.venv/Scripts/python.exe -m pytest -q --basetemp .cache/pytest-a --ignore=tests/test_retrieval.py
.venv/Scripts/python.exe -m pytest -q --basetemp .cache/pytest-b tests/test_retrieval.py
```

Evaluation uses the same frozen QA file and Top-5 query path on each of the eight collections. The script records the dataset and LF-normalized QA SHA-256, model revision, versions, platform, and per-question rank and retrieval results. Hit Rate@5 counts a query once if any retrieved chunk has the labeled document and an inclusive physical evidence page. MRR@5 averages `1 / first_hit_rank` with zero for misses. Hit Rate@3 uses the first three results. All Evidence@5 checks whether every listed locator is represented, which is useful for multi-source questions. Page-level hits may retrieve an adjacent chunk that omits the answer. Latency includes query encoding, Chroma count and search, and result mapping. One untimed query per configuration warms the model and collection, and the timed pass is sequential.

The [QA review record](retrieval_qa_review.md) links each item to its evidence pages. The [gold file](../data/evaluation/qa_gold.jsonl) contains the reference answers and marks all 24 rows `agent_verified` after the delegated source review. Rerun evaluation after editing the questions or evidence.

The B suite passed 12 tests. A's original suite ran with `RAG_TEST_REAL_MODEL=1` and reported 81 passed and 1 failed. The failing `test_isolated_benchmark_repeated_records_and_baseline_compatibility` hits the same Windows byte-comparison issue described above. The combined run reported 93 passed and 1 failed. `--basetemp` puts pytest fixtures in the writable checkout for sandboxed runs.

## Measured results

All eight collections were rebuilt from dataset `pilot5_8321c43ee6b1`. Their record counts and LF-normalized JSONL SHA-256 values matched A's tracked benchmark. Each collection passed A's persisted record and vector checks after both writes. The evaluation below used the pinned MiniLM revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf` on CPU with four Torch threads. The same 24 source-reviewed QA rows were queried once per configuration, for 192 timed queries. See [full ranks and run metadata](retrieval_results.json).

| Cleaning | Size | Overlap | Records | Hit@3 | Hit@5 | MRR@5 | All evidence@5 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 150 | 0 | 753 | 37.50% | 45.83% | 0.3243 | 41.67% | 30.400 |
| baseline | 150 | 30 | 885 | 62.50% | 62.50% | 0.4236 | 54.17% | 28.215 |
| baseline | 220 | 0 | 536 | 50.00% | 58.33% | 0.4493 | 54.17% | 28.596 |
| baseline | 220 | 30 | 588 | 50.00% | 62.50% | 0.4181 | 54.17% | 29.339 |
| enhanced | 150 | 0 | 749 | 37.50% | 45.83% | 0.3451 | 41.67% | 28.879 |
| enhanced | 150 | 30 | 874 | 62.50% | 62.50% | 0.4722 | 54.17% | 31.447 |
| enhanced | 220 | 0 | 534 | 54.17% | 58.33% | 0.4549 | 54.17% | 17.851 |
| enhanced | 220 | 30 | 584 | 50.00% | 62.50% | 0.3972 | 54.17% | 29.773 |

- **Cleaning.** Paired baseline and enhanced configurations retrieved the same number of labeled pages at Top-5. Enhanced cleaning improved MRR most at 150/30, from 0.4236 to 0.4722. B06 and B07 moved from rank 2 to rank 1 there, and B22 moved from rank 3 to rank 2. At 220/30 MRR fell from 0.4181 to 0.3972.
- **Chunk size.** At zero overlap, 220 tokens raised Hit@5 from 11/24 to 14/24 in both arms. At 30-token overlap both sizes reached 15/24. The 150-token chunks ranked first hits earlier on average at 30-token overlap in both arms.
- **Overlap.** At 150 tokens, adding 30 tokens of overlap gained four Top-5 hits in each arm and increased MRR. At 220 tokens it gained one Top-5 hit and lowered MRR in both arms. B09 dropped from rank 1 to a miss at 220 tokens, while B03 gained a hit on one of its two evidence pages. Overlap increased stored chunks in each paired comparison.
- **Latency.** The eight means ranged from 17.851 to 31.447 ms in this single sequential pass. Timing and ranking differences describe this Windows run and the 24 reviewed labels.

### Real Top-5 interface checks and cases

Direct calls to the installed `retrieve()` returned five chunks per question for B01, B02, B03, B04, B05, B06, B11, B15 and B22 on the default enhanced 150/0 collection. The check verified ascending distance, nonempty chunk IDs and text, official URLs, valid physical pages and agreement with A's temporal catalog. The table gives the first result and first labeled page for five of those calls.

| QA | First result | First labeled page rank |
| --- | --- | ---: |
| B04 | HKMA 2026 p. 1 | Miss |
| B05 | HKMA 2019 p. 4, `superseded` | 1 |
| B06 | FSB 2026 p. 15 | 2 |
| B15 | FSB 2026 p. 8 | Miss |
| B22 | BIS FSI Insights No. 63 p. 27 | 5 |

- **B05, historical evidence success.** In enhanced 150/0, `hkma_20191101_ai_principles_p4_c2_fixed_150` ranks first and contains the suspension and fallback passage. Its `superseded` status is visible to C.
- **B04, version and chunk-boundary failure.** Both 150-token enhanced collections miss the 2019 cybersecurity page. Enhanced 220/30 ranks the right physical page first, but the rank-1 chunk covers the closing paragraphs. The rank-3 chunk from the same page contains the two cybersecurity threats. This illustrates the gap between page-level and text-level evidence.
- **B06, page hit versus supporting text.** Enhanced 150/0 retrieves the 2026 HKMA purpose paragraph with the supersession statement at rank 2. Enhanced 220/30 places the correct page at rank 1, but that chunk starts in the background section. Its rank-4 chunk contains the actual statement.
- **B24, partial cross-document coverage.** Every configuration finds the HKMA page that names the FSB report at rank 1. None returns the labeled FSB physical page 6 in Top-5, so all eight score a first hit and zero complete evidence for this question.
