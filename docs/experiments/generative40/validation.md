# Frozen branch validation — 2026-11-06

This snapshot was prepared on Windows10 build26200 / Python3.11.15 from
`origin/main` commit `8f8d5d134db456eda1a0212817bd9a3436d94c8a` on
`feature/retrieval`. The default QA/UI files are unchanged. The experimental
runtime's eleven staged Git blobs match their frozen SHA256 manifest; the six
original application files also match the approved protocol hashes.

## Executed checks

| Check | Actual result |
| --- | --- |
| Existing A/B/C pytest suite, with real local MiniLM smoke test enabled | 137 passed |
| Full40 isolated orchestration preflight | 30 checks passed;80 mock dispatches;360 main-stage events |
| Explicit authorization and formal-mode metadata checks | 5 passed, synthetic transports only |
| Preserved retrieval candidate budget/text checks | 3 passed |
| Installed dependency constraints (`uv pip check`) | All116 packages compatible |
| Frozen report and local evidence verification | 17 delivery files,7 available source chunks and all320 saved context texts verified |
| New file scan | No provider/GitHub token or personal machine path found |
| Git whitespace check | Passed |

The actual full-suite command was:

```powershell
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:RAG_TEST_REAL_MODEL = '1'
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Cache-provider writes were disabled because the existing `.pytest_cache` was not
writable. The real MiniLM test uses cached weights, synthetic test PDFs and a
temporary database. No official corpus/index was rebuilt and no new model API
request was made.

## Environment and corrections

The initial full-suite collection identified missing Streamlit. The existing app
pin `streamlit==1.66.0` was installed into the local virtual environment using the
existing Pillow12 override. Historical dependency locks were not rewritten.
Observed versions include httpx0.28.1, python-dotenv1.2.4, PyMuPDF1.26.6,
transformers4.57.1, sentence-transformers5.1.2, Chroma1.3.5, torch2.15.0,
Pillow12.0.0, pandas3.1.1 and pyarrow26.0.1. Transitive versions may differ from
the historical macOS lock; the installed Windows environment passed dependency
compatibility and the complete suite.

The existing Phase2.6 baseline-compatibility test exposed default CRLF translation
in `benchmark.py`. The only ingestion-source change is explicit LF when writing
benchmark JSONL, matching the original pipeline writer and preserving deterministic
bytes across platforms. Public interfaces, chunk content, collection contracts,
existing outputs and historical scores were not changed.

One intermediate complete-suite attempt encountered Chroma's native `Nothing
found on disk` reader error in the foreign-collection rebuild test. That test
passed in isolation, and a fresh full-suite process then passed all137 tests.
No Chroma source/workaround was added. The final run emitted52 existing legacy
embedding-configuration deprecation warnings; it had no skipped or failed test.

The free experiment harness was also made portable for a new checkout: it creates
parent output directories and reads UTF-8 explicitly; authorization tests infer
the checkout's `src` and use a bounded local temporary parent. These changes do not
alter the frozen runtime/prompt/message hashes or authorize a real run.

## Published scope

The branch contains isolated experiment/retrieval code, public-source frozen
inputs, evaluator references, reviewed summaries, report and diagnostic evidence.
Reviewer bookkeeping in the baseline scoring snapshot is standardized; original
judgments and source checks are retained. It excludes real approval files, secrets,
raw HTTP/stage/checkpoint logs, PDFs, databases, environments and model caches.

The reported69-call complete40 experiment remains frozen at27/30 core,25/30 full
claim support and10/10 refusal. Offline diagnosis did not replay ANN ranking and
does not establish a retrieval repair. No default deployment or further paid
experiment is included in this branch push.
