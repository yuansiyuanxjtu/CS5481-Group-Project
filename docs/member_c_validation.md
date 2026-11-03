# Member C validation log

Environment: macOS 26.6.2 arm64, CPython 3.11.18, 2026-11-03 (Asia/Hong_Kong).

## Verified locally

- All five official PDFs downloaded and matched A's pinned SHA-256 values; 165 physical pages.
- Original JSONL outputs: 753 `fixed_150`, 588 `fixed_220_overlap_30` chunks.
- Both original stores and eight isolated Phase 2.6 experiment collections rebuilt.
- Every baseline/enhanced collection passed A's input, citation, vector and repeat-ingestion checks.
- Real B retrieval returned five distance-ordered hits with original source metadata.
- School model list authenticated successfully; a real B06 question produced a cited answer.
- Streamlit browser interaction produced the same grounded answer, source card and original PDF link.
- Browser source cards show title, publication date, physical page, document ID, chunk ID,
  original URL, supporting quotation and explicit unknown-status label.
- 27 gold evidence locators and 18 generated answer quotations checked against checksum-pinned
  physical PDF pages: 45 checks, zero missing quotations.
- The new combined dependency lock matches the installed environment, and dependency consistency passes.
- A's ingestion/storage APIs and historical dependency locks are unchanged. C's combined lock
  overrides Pillow 13 with 12.0.0 for Streamlit compatibility and marks uvloop non-Windows only.

## Automated tests

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
OMP_NUM_THREADS=4 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

Final result after adding resume and total-deadline checks: **137 passed, 57 dependency deprecation warnings, no failures**.
This includes A's 82 tests, B's 12 tests and C's 43 tests. Real cached MiniLM integration is enabled.
Tests are engineering checks, not a claim of 100% answer accuracy.

## Security and artifact checks

`.env`, `.env.*` backups, `.venv`, PDF files, model caches, processed chunks and Chroma stores
are ignored. Only `.env.example` is tracked. Before committing, compare staged content against
the actual local key without printing it. Generated run metadata excludes credentials.

The school API failure is tracked separately from insufficient knowledge; incomplete metrics
are null. See `answer_evaluation_analysis.md` for actual errors and recovery commands.
Official DeepSeek evaluation must be saved as a separate run, not merged into the school results.

## Completed official-provider run

The official provider `deepseek-flash` completed all 24 gold plus five OOD questions after
a recorded timeout continuation. Draft source review: 8 correct, 3 partial, 13 incorrect;
strict accuracy 33.33%, OOD explicit refusal 5/5. Independent human confirmation is pending.
All 56 source checks pass for the official run. A separate six-question real demo is saved.
No school outputs were used to fill missing official-provider answers.

Final browser QA exposed a response that kept sending data without completing. C's
adapter now uses cancellable asynchronous HTTP under a synchronous interface, bounding
the entire call as well as network inactivity. A dedicated test verifies cancellation.
This transport-only hardening preserves the prompt/request payload and recorded experiment
answers; source hashes in the run correctly identify the pre-hardening execution version.
