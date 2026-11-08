# OfoxAI diagnostics: cleanup and cancellation fixes

8 November 2026. Local implementation and offline verification only. Branch `codex/ofox-failure-diagnostics`, HEAD/base `2b2073cdeb1d14eea7635fcd7550632db1fb14e2`, isolated worktree `/Users/yuansiyuan66/.codex/worktrees/ofox-demo-guard/cs5481-final-acceptance-20261108`.

## Original failures reproduced before editing

The unchanged independent probe file was rerun before any fix. Result: **2 failed, 13 passed**. Original review reports, probe source, initial logs and historical registry were preserved.

| Finding | Failing condition and expected behavior | Observed before fix | Root cause and original source locations |
| --- | --- | --- | --- |
| D1 | Valid synthetic selection response followed by HTTPX ReadError in transport closure. Preserve the valid response observation and separately diagnose cleanup failure. | QA `llm_error`, one consumed attempt, stopped session, but only an `ok`/`complete` diagnostic in the audit and first result. | Response diagnostic was finalized at `ofox_demo.py:110–136`; `aclose` at :138–140 ran outside that capture; client context exit at :162–173 converted its error without adding diagnostics. |
| D2 | Ordinary CancelledError without an expired deadline. Classify as `cancelled`, preserving cancellation propagation and consumed reservations. | `exception_category(CancelledError())` returned `timeout`. | `ofox_diagnostics.py:75–76` classified cancellation and timeout together, without deadline evidence. The earlier repository assertion reinforced that equivalence. |

These findings diagnose the patch, not the historical EXP11 incident. Its original cause remains unexplained. The operator's later successful DNS/TCP/TLS/root-GET observations do not establish model API compatibility or past request receipt/billing.

## Targeted changes

Exactly six files were changed/added in this follow-up:

| File | Change |
| --- | --- |
| `src/rag_app/ofox_demo.py` | Separate cleanup observation; idempotent closure; retain primary request exception when cleanup also fails; Ofox-only owned deadline context; pass affirmative deadline-expiry evidence to classification. |
| `src/rag_app/ofox_diagnostics.py` | Add bounded `cancelled` category and `cleanup` stage; distinguish ordinary cancellation from confirmed deadline expiry. |
| `src/rag_app/demo_budget.py` | Append-only cleanup diagnostic extension for new stores, atomic stop on cleanup failure, merged bounded accessor; first-result diagnostic bound raised to 12 observations without changing six-attempt ceiling. |
| `tests/test_ofox_diagnostics.py` | Correct the ordinary-cancellation assertion; retain the existing genuine overall-deadline regression. |
| `tests/test_ofox_lifecycle.py` | Ten focused lifecycle regression cases. |
| `docs/ofox_diagnostics_fix_verification.md` | This verification report. |

The earlier patch also includes its original diagnostics helper/tests/documentation and the test-only registry-isolation fixture in `tests/conftest.py`; that fixture was not changed in this follow-up. `docs/ofox_diagnostic_patch_review.md` and `docs/ofox_diagnostics_independent_review.md` remain immutable historical accounts of the prior fingerprint/results. This report supersedes their current-state description for D1/D2. The preexisting local preflight report remains excluded from the intended publication patch.

### D1: preserve response and cleanup as distinct observations

The original response record remains INSERT-only in `attempt_diagnostics_v1`. Cleanup failures append to `cleanup_diagnostics_v1`, keyed by the same consumed ordinal. They preserve the response status, response/body flags, finish observation and safe request-ID digest while reporting a separate cleanup-stage category. They do not alter the original attempt state/usage or reserve another attempt. A valid response may therefore retain `state=ok` while a separate cleanup failure makes the overall session stopped; consumers must inspect the lifecycle/QA outcome as well as the response row.

Appending cleanup evidence and setting the session stopped share one transaction. The new table is created only during explicit provisioning of new synthetic/future stores. No existing registry migration or repair is performed. The accessor merges response and cleanup observations in ordinal/event order, at most 12 rows: up to six of each. In-memory and first-result summaries are capped at 12 as well; this is an observation limit, not a request limit.

Cleanup is attempted once. Its failure propagates if no request exception is already in flight. If a primary request error/cancellation already exists, that original exception remains primary and the secondary cleanup evidence is retained separately. This avoids converting an HTTP rejection into a cleanup-only generic error. Secondary cancellation during cleanup follows this same explicit precedence; a sole cancellation is never silently converted to a normal result.

If cleanup diagnostic persistence fails, both cleanup and audit-failure summaries are retained in bounded memory and the original cleanup exception/cancellation is preserved. If possible, the first QA failure result persists those summaries. A consumed reservation is never freed. If writes remain unavailable, the already-running/interrupted case blocks continuation even if the stop-state write could not commit.

### D2: cancellation versus deadline evidence

`exception_category` returns `cancelled` for ordinary CancelledError. HTTPX/builtin timeout exceptions still map to `timeout`. Cancellation maps to `timeout` only when the Ofox client's owned `asyncio.timeout` context reports `expired()`.

The Ofox override keeps the configured overall request limit, including cleanup, without changing the shared baseline/DeepSeek ChatClient. The owned context converts its own expired-deadline cancellation to TimeoutError; ordinary external cancellation propagates unchanged. The transport records the corresponding category before rethrowing. No cancellation text or exception representation is serialized.

Before reservation, no ordinal, transport dispatch or provider attempt is invented. A case already claimed before interruption remains non-resumable under the existing guard. After reservation, a failed/cancelled response retains its consumed attempt; cancellation during cleanup leaves both the response and separate cleanup observations. No retry/recovery is introduced.

## New regressions and results

Ten cases in `tests/test_ofox_lifecycle.py` cover:

- Successful HTTP response followed by cleanup failure, retaining both durable observations and the first result.
- HTTP 403 followed by cleanup failure; retain rejection/status and stop with one attempt.
- Original HTTP exception remaining primary over a secondary cleanup exception.
- Actual task cancellation while awaiting transport and while reading a response body, with cancellation arguments/semantics preserved and no secret serialization (two cases).
- Cancellation before reservation, zero attempts and no transport construction.
- Cancellation during cleanup after a valid response or an existing HTTP failure, retaining earlier evidence (two cases).
- Genuine application deadline expiry while cleanup is pending, distinguished from ordinary cancellation.
- Cleanup-audit INSERT failure, preserving the response record, adding audit diagnostics where possible, and blocking continuation.

Every case uses synthetic credentials, MockTransport/subclasses, frozen local evidence and temporary SQLite stores. Assertions check consumed attempt counts, no extra dispatch/retry, blocked duplicate/next-case submissions, original response-row preservation and secret-safe output. Existing tests continue to cover HTTPX timeouts, overall deadlines during dispatch, seventh-attempt blocking, source mismatch, concurrency, provisioning fences and immutable first results.

Evidence directory:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostics-fixes-20261108`

Exact commands executed, from the isolated worktree:

```sh
ARTIFACT_DIR=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostics-fixes-20261108
PROBES=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostics-independent-20261108/test_review_probes.py
python3 "$ARTIFACT_DIR/run_offline.py" before_probes -m pytest -q -p no:cacheprovider "$PROBES"
python3 "$ARTIFACT_DIR/run_offline.py" focused_first -m pytest -q -p no:cacheprovider tests/test_ofox_diagnostics.py tests/test_ofox_lifecycle.py tests/test_ofox_demo.py tests/test_ofox_provisioning.py
python3 "$ARTIFACT_DIR/run_offline.py" after_probes -m pytest -q -p no:cacheprovider "$PROBES"
python3 "$ARTIFACT_DIR/run_offline.py" full_first -m pytest -q -p no:cacheprovider tests experiments
```

The wrapper runs the worktree `.venv/bin/python` (Python 3.11.15), with dotenv disabled, inherited provider keys blanked, offline model flags and a clean allowlisted environment. An audit hook prevents external DNS/socket connections, including inherited subprocesses. Cached real MiniLM verification was enabled. No connectivity or provider call was attempted. Logs are exclusive-created, with matching argv/exit-code/duration JSON files; use fresh labels for reproduction.

| Run | Actual result |
| --- | --- |
| Unchanged probes before edits | **2 failed, 13 passed**, 0.79s; both original findings reproduced. |
| Focused diagnostic/lifecycle/security suite after edits | **94 passed**, 8.52s; 5 dependency deprecation warnings. |
| Same unchanged independent probes after edits | **15 passed**, 0.79s; 5 warnings. |
| Complete repository and experiment suite | **249 passed**, 17.99s; 57 warnings, no skips. Includes all previous 239 cases and 10 new cases. |
| Whitespace validation | `git diff --check` passed. |

No post-fix test invocation failed in this follow-up. The before-fix failures and previous implementation/review failures remain preserved, not replaced by successful logs. Production/test code was not changed between the focused, post-fix probe and full-suite runs.

## Security and historical preservation

The following remain unchanged: fixed canonical registry path; provider `https://api.ofox.ai/v1`; endpoint `/chat/completions`; model `openai/gpt-6-luna`; `ofox_joint_pairs8` profile; exact three-case order; 1,200 completion limit; low reasoning effort; JSON mode; streaming disabled; pinned OpenAI route and empty fallback; zero retries; TLS verification; `trust_env=False`; redirects disabled; configured 120-second live deadline; six total attempts; source/frozen-evidence binding and provisioning fences.

No raw request/error bodies, Authorization headers, API keys, proxy credentials or environment values were added to diagnostics. New category/stage values are finite allowlisted enums. A response-level `ok` is explicitly distinct from lifecycle/QA success. Missing usage remains unknown billing, including after cancellation or cleanup failure.

The old stopped registry was only hashed/stat'ed, never opened via SessionLedger or migrated. Its SHA-256 remains `8e48af9ec8958c1f86d0ac86c23902a0458ccd544b4711dfb5c6da9c0e69da23`; mtime remains `1794121344846265568` ns. No approval content or credential was read. No new live session or approval was created.

`before.json` and `preservation.json` confirm that only the four preexisting source/test files listed above changed during this follow-up. All historical experiments, source/frozen evidence, retrieval code, prompts, scores, prior verification reports and the local preflight report remain byte-identical. The new test file and this report are the only added repository files in this follow-up. Test-created synthetic registries are temporary and never the canonical operator registry.

Source fingerprint before this follow-up: `4de7fa9c60af2d02efb79d7e6d678ab33b82e2ca696d7b7000e51496d19b948c`.

Current uncommitted source fingerprint: `9c7982aa05fcf00552671220768235d4570db38c980474100386ce4bc6d3db80`.

The original live approval fingerprint remains `000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee` in its preserved historical evidence; it was not rewritten to authorize changed code. Source drift still blocks before dispatch. No reset, relocation, successor controller or path override was introduced.

## Remaining limitations and publication readiness

The original live EXP11 failure remains unexplained. Provider route/model/parameter compatibility and actual billing remain unverified. Root-endpoint HTTP 200 is not Chat Completions acceptance. These tests establish synthetic failure handling only.

A crash or continuing audit failure may prevent a terminal diagnostic/first QA result from being persisted; reservations remain consumed and interrupted cases remain blocked. Cleanup diagnostic timestamps describe the newly captured cleanup observation, not a measurement of network receipt, inference or billed duration. If the task is cancelled with no prior request error, cancellation propagates rather than yielding a synthetic normal QA result; durable observations survive where writes succeed.

The diagnostic extension is not an old-store migration and does not permit reuse of the permanently stopped acceptance session. Any future live test still requires a separately designed/versioned and independently reviewed successor mechanism that recognizes the immutable old incident, plus fresh explicit scope/attempt/financial authorization. Creating another approval or renaming a session cannot authorize a new paid run.

D1 and D2 are corrected and their unchanged probes pass. This patch is ready for final independent publication review, not yet committed/published, and not authorized for live execution. No commits, pushes, merges or tags were created.

**READY FOR FINAL PUBLICATION REVIEW**
