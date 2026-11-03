# Member C: Grounded QA & Demo

Completed direct-provider results: [official experiment analysis](answer_evaluation_official_analysis.md),
[24+5 real QA records](answer_evaluation_official_completed.json),
[per-question draft grading](answer_evaluation_official_completed_ratings.csv),
[metrics](answer_summary_official.json), [six demo records](demo_records.json), and
[validation log](member_c_validation.md). Human team review remains required.

C calls B's `Retriever.retrieve(question, top_k, collection=..., arm=...)` and preserves A's
document IDs, exact chunk text, official PDF URLs and one-based physical PDF page numbers.
The current C branch includes B commit `5fbfbb0` as a dependency; B's PR should be reviewed
before the C PR is merged. A's ingestion/storage APIs and historical lock files are unchanged.

## Install and start (macOS / Python 3.11)

From the repository root, create a Python 3.11 virtual environment. A's phase2 lock pins
Pillow 13, whereas Streamlit 1.66 requires Pillow <13. For the combined C environment,
use the separately recorded `requirements-app-lock.txt`; do not successively install the
old phase2 lock over it. `requirements-app-overrides.txt` explains the sole overridden
historical pin (Pillow 12.0.0). The combined environment must pass A/B/C tests.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-app-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
cp .env.example .env
# Edit .env locally: fill LLM_API_KEY. Never paste it into a terminal command or commit it.
```

Follow README's ordered **First team checkout** commands to acquire only the five pinned
PDFs, prepare MiniLM, generate original JSONL/DBs and build `phase26_reproduction`. Skip
its old dependency installation steps when using C's combined lock. No models/PDFs/DBs
are shipped through Git. A download can refresh acquisition timestamps in the tracked
pilot catalog; inspect that diff rather than inadvertently committing it.

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open `http://localhost:8501`. Submit an English question and inspect the answer, supporting
quotations and original PDF links. Source cards label **physical PDF pages**, not printed
page labels. Some PDF viewers ignore URL `#page=N`; the displayed physical page remains
the authoritative locator. Verify links in the presentation browser before class.

## Configuration and provider replacement

`.env` is ignored. `.env.example` contains no credentials. The final user-selected provider
is direct DeepSeek (`https://api.deepseek.com`, model ID `deepseek-flash`) with an official
DeepSeek API key and `thinking=disabled`. The adapter sends one HTTPS Chat Completions
request, JSON mode and temperature 0.
The earlier school gateway (`https://llm.cs.cityu.edu.hk/v1`, model
`CS5351/DeepSeek-V4-Flash`, blank `LLM_THINKING`) became deployment-unavailable during
the first evaluation. That partial run remains separately archived; it is not mixed into
the official-provider experiment.
It does not call search or other tools. Restart Streamlit
after changing environment/model/key so the cached service reloads.

For another compatible provider set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, and
leave `LLM_THINKING=` if that provider does not support DeepSeek's `thinking` parameter.
For direct DeepSeek use `https://api.deepseek.com`, `deepseek-flash`, a separately issued
official DeepSeek key, and optionally `LLM_THINKING=disabled`. School virtual keys are
valid only at the school gateway, not at the upstream vendor's endpoint.
Set `LLM_JSON_MODE=false` only if the provider lacks JSON mode; output still must pass
the same JSON schema and citation checks. Other API formats need a new `generate()` adapter.

Cost bounds: one call per submitted question, no automatic retries, 1..10 hits,
40,000 characters total context, 128..4,096 output tokens (default 1,200), finite
HTTP timeouts plus a cancellable total request deadline (example configuration: 60 seconds).
The total deadline also bounds provider responses that keep sending whitespace/keepalive data.
Evaluation stops after the first API or
retrieval service failure. These are request bounds, not an account-wide spending limit.

## Evidence and refusal rules

1. Validate B's result fields and join the exact run's temporal catalog by document ID;
   verify the snapshot hash and source URL. Keep `unknown` and `superseded` visible.
2. Assign IDs to the evidence actually supplied to the model.
3. Ask for concise atomic claims with exact source quotations, or explicit refusal if
   evidence is missing, insufficient for the full question, or unresolvedly contradictory.
4. Reject invalid JSON, unfinished output, missing citations, unknown IDs, generated
   links/IDs in claim text and quotations not present in the cited chunk.
5. Render citations from the original records, never model-generated provenance.

`answered`, `insufficient_evidence`, `invalid_input`, `retrieval_error`, `llm_error`, and
`invalid_output` are separate states. API failure does not count as a refusal.
Exact quotations prove source membership, not semantic entailment. Prompt constraints
do not guarantee zero hallucination. Human grading must check every claim against the
quoted source, including missing qualifiers and version differences.

`RAG_MAX_DISTANCE` is blank by default: no uncalibrated numeric cutoff is presented as
an answerability probability. If B/C calibrate one on a separate development set, record
it and set it explicitly; do not tune it on the final gold test set. Default retrieval is
B's current `enhanced/fixed_150`, Top-5. Other collections remain configurable. The
150/30 run has stronger B metrics, but adopting it as the demo default is a team decision.

## Formal answer evaluation

The shared B file contains 24 gold QA with source locators; C adds 5 explicitly outside-
knowledge-base questions. B's current review status is `agent_verified`, not independent
human verification. A group member should confirm the gold references against the PDFs.

```bash
.venv/bin/python scripts/eval_answers.py run --output docs/answer_evaluation_new.json
```

This makes at most 29 real requests, saves actual answers, evidence, citations, provider-
reported model/usage, timing, run/source/prompt/QA fingerprints, and creates
`docs/answer_evaluation_new_ratings.csv`. It checkpoints each result and refuses to overwrite
earlier runs. Review each row in the CSV and fill `verdict`, `citation_verdict`,
`failure_stage`, `reason`, `reviewer`. Use a new output name to rerun; never silently replace
an inconvenient result. An infrastructure failure leaves subsequent records `not_run`.

Resume into a **new** output path after resolving a service failure:

```bash
.venv/bin/python scripts/eval_answers.py run --resume docs/answer_evaluation_new.json \
  --output docs/answer_evaluation_continued.json
```

Resume retains all answered/refused/invalid-output records; only infrastructure failures
and `not_run` records are eligible for retry. Question, prompt, source, retrieval and
generation settings must match. A changed network timeout is recorded per request.
Prior attempts and their fingerprint remain linked in the new run. Never resume to
select a nicer answer for a completed test question.

Grading:

- `correct`: all required facts correct, source-supported, with correct citations.
- `partial`: some requested facts correct but key detail/evidence coverage missing.
- `incorrect`: wrong/unsupported key fact, incorrect citation, false refusal, or service failure.
- Citation grading: `valid`, `invalid`, `not_applicable` (refusal/no citations), `pending`.
- Failure stage: `none`, `retrieval`, `generation`, `citation`, `service` (describe overlaps in reason).

Strict answer accuracy is correct/24. Optional partial credit is (correct + 0.5*partial)/24.
Keep all gold questions in the denominator. Report OOD refusal rate independently, without
counting API/retrieval failures as successful refusals. The summary leaves accuracy null
until every row has a reviewer, reason and completed grade. It rejects correct/partial
ratings for service failures and correct ratings for invalid citations.

```bash
.venv/bin/python scripts/eval_answers.py summarize \
  --run docs/answer_evaluation_new.json --ratings docs/answer_evaluation_new_ratings.csv \
  --output docs/answer_summary_new.json
```

Analyse at least three actual failures/limitations in the final report: retrieval misses,
retrieved-but-unsupportive chunks, partial cross-document evidence, semantic citation
errors, false refusals or service errors. Do not invent failure observations before a run.

## Demo and regression validation

```bash
.venv/bin/python scripts/eval_answers.py run --demo --output docs/demo_records_new.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 \
  .venv/bin/python -m pytest -q
```

The demo selects six real questions: B02 (single document), B05 (historical 2019),
B06 (supersession), B23 (cross-document comparison), B24 (incomplete multi-source
retrieval), OOD01 (no evidence). These are run records, not a substitute for the full
evaluation. Keep screenshots of the actual Streamlit answer/source/error states.

The initial five mock chunks exist only in `tests/test_qa_app.py` and use fictional
`example.invalid` sources. No mock retrieval or scripted answers are presented as a
real-corpus demo. Streamlit tests cover submit, blank input, missing key, grounded
answer/source display, historical warning, refusal, and each service failure state.

## B/C integration decisions to confirm

- Freeze default arm/collection/top-k and QA fingerprint.
- Preserve B's exception behavior and 256-token query limit; no silent truncation.
- Reuse one Retriever/model instance and resolve paths from the project root.
- Share OOD distances before any threshold calibration.
- Confirm human review of the 24 gold QA and review C's answer/citation judgments.
- Review the Pillow compatibility override in the shared environment.
- C completion requires real records, graded accuracy, five OOD outcomes, at least three
  errors/limitations, screenshots or five demo records, passing regressions and a reviewed PR.
