# OfoxAI failure-diagnostics independent review

8 November 2026. Review only; no production changes, provider connections, credential access, live provisioning, commit, push or merge.

## Reviewed version and contents

- Branch: `codex/ofox-failure-diagnostics`.
- HEAD/base: `2b2073cdeb1d14eea7635fcd7550632db1fb14e2`.
- The patch is uncommitted; HEAD alone does not identify its contents. Reviewed application/frozen-input fingerprint: `4de7fa9c60af2d02efb79d7e6d678ab33b82e2ca696d7b7000e51496d19b948c`.
- Worktree: `/Users/yuansiyuan66/.codex/worktrees/ofox-demo-guard/cs5481-final-acceptance-20261108`.

The complete tracked diff changes `src/rag_app/ofox_demo.py`, `src/rag_app/demo_budget.py` and `tests/conftest.py`. New patch files are `src/rag_app/ofox_diagnostics.py`, `tests/test_ofox_diagnostics.py`, `docs/ofox_exp11_failure_postmortem.md` and `docs/ofox_diagnostic_patch_review.md`. This review adds only `docs/ofox_diagnostics_independent_review.md` in the repository. The preexisting untracked `docs/ofox_live_preflight.md` was examined as historical context, preserved and excluded from the proposed patch.

The diff is limited to diagnostics, atomic audit persistence, synthetic tests and related reports. No changes to model, endpoint, generation parameters, dependencies, UI, retrieval algorithms, prompts or frozen scores were found. Exact reviewed file hashes were captured before testing and remained unchanged afterward.

## Findings requiring correction

No critical security vulnerability or authorization/budget bypass was reproduced. Two **P2 diagnostic correctness findings** remain. They concern the purpose of this patch: identifying failures accurately rather than replacing one generic failure with misleading evidence.

### D1 — Transport cleanup failure leaves only a successful diagnostic

**Location:** `src/rag_app/ofox_demo.py:110–136`, `:138–140`, `:162–173`.

`handle_async_request` commits an `ok` terminal diagnostic and emits it before the client context closes. `GuardedTransport.aclose()` delegates to the upstream transport without diagnostic capture. If upstream cleanup raises an HTTPX error, `_request` converts it to an LLMError, but the only persisted/returned diagnostic still says `category=ok`, `failure_stage=complete`.

**Independent reproduction:** a MockTransport subclass returned the existing valid synthetic selection response and raised a synthetic `httpx.ReadError` only in `aclose()`. The service returned `llm_error`; one selection request was consumed; no generation occurred; the session stopped. Both its stored attempt diagnostic and returned first-result diagnostic list contained only the successful response diagnostic. The synthetic error text did not leak.

The successful envelope observation is valid, but it is not a complete terminal account of this failed application request. This leaves another generic-error path without a diagnosis and could direct an operator away from the actual cleanup failure.

**Required correction:** retain the successful response observation, but also capture a bounded, sanitized cleanup/client-lifecycle failure with its stage and originating attempt ordinal, and include it in the first failure result where persistence is available. Do not overwrite historical records, release the consumed attempt, retry the request, or hide an audit failure while recording the additional evidence. Add a mock cleanup-failure regression verifying both observations and blocked continuation.

### D2 — Cancellation is treated as proof of timeout

**Location:** `src/rag_app/ofox_diagnostics.py:75–76`; corresponding assertion in `tests/test_ofox_diagnostics.py:193`.

`exception_category` maps every `asyncio.CancelledError` to `timeout`. Cancellation can instead come from an explicit operator/event-loop shutdown or another caller cancelling the task. The exception alone does not establish a deadline. The existing test asserts this inaccurate equivalence, so a green suite does not catch it.

**Independent reproduction:** an ordinary `asyncio.CancelledError()` with no timeout context produces `timeout`. A separate independent assertion that cancellation must not imply timeout failed. The existing one-second total-deadline regression still passes, but it cannot justify applying that label to all cancellation.

**Required correction:** use a bounded cancellation/unknown classification unless the owning deadline boundary supplies affirmative timeout evidence. Keep timeout classification for actual HTTPX/builtin timeout exceptions. Add separate tests for explicit cancellation and a confirmed total-deadline expiration; both must retain consumed reservations and fail closed. Do not infer the cause from exception messages.

These findings do not show that the historical EXP11 failure was caused by cleanup or cancellation. Neither path was observable in the original record.

## Diagnostic accuracy and privacy assessment

The following existing paths passed the focused tests and/or independent probes:

| Observation | Assessment |
| --- | --- |
| DNS / TLS | Class-based bounded cause-chain checks; no message guessing. Lost causes correctly limit precision to generic connection failure. |
| Connect / proxy / read-write failures | Bounded categories; no HTTP status invented without a response. |
| HTTPX timeouts | Timeout category; response status retained when headers precede body-read failure. D2 concerns generic cancellation separately. |
| HTTP 400, 401, 403, 429, 502, 503 | Response flag and actual status retained; malformed/non-JSON error bodies do not become raw logs. |
| Provider error codes/types | Fixed allowlist; unknown strings, nested objects and instructions omitted. |
| Invalid JSON / schema | Distinct envelope failures; untrusted content omitted. |
| Wrong returned model | Mismatch category; arbitrary returned model string not copied. |
| Non-stop finish / empty content | Bounded finish values or `other`; invalid content rejected. |
| Budget / audit failure | Pre-dispatch refusal or consumed uncertain reservation preserved; safe in-memory failure summary where possible. |
| Successful stages | Separate selection/generation observations, HTTP status and attempt ordinal; D1 leaves cleanup outside this coverage. |
| Missing usage | `partial_or_unknown`, not a claim of zero tokens or zero billing. |

The diagnostic schema is rebuilt at collection and persistence boundaries. Strings are restricted to finite enum sets, normalized bounded timestamps and a fixed-length digest. Attempt ordinals and HTTP status are bounded integers; flags are strict booleans. Raw request bodies, provider messages, exception messages, Authorization headers, environment variables and proxy credentials are not serialized by diagnostics. Request IDs are restricted by format/length, checked for the in-memory credential and retained only as SHA-256 digests. Hostile synthetic headers were omitted. No execution/evaluation of provider text or uncontrolled string log sink was introduced.

The record is bounded, but this is not a new response-body size limit: the existing HTTP response still must be read/parsed. Diagnostics cover transport/envelope processing; planner, answer and citation validity remain separate QA-result checks. A response-level `ok` alone never establishes a supported answer, provider billing, or successful completion of every client lifecycle operation.

## Authorization, audit and compatibility

- Reservation remains durable before transport construction/dispatch. Failed and uncertain requests retain their ordinal.
- The six-attempt ceiling, exact case order, duplicate/concurrent/interrupted-case checks, source fingerprint, canonical path binding, provisioning fence and first-result INSERT-only behavior are preserved.
- Application entry points still use the fixed registry and check it before reading configured credentials/loading the real transport. No environment override, retry, fallback, new network probe or recovery mechanism was added.
- Existing stopped/source-mismatched synthetic stores refused execution. Relocation, symlink, source-drift, seventh-request and provisioning crash/fence tests passed.
- Diagnostic insertion and terminal update share a transaction. An injected INSERT failure rolled back the terminal update and left the existing reservation consumed; the interrupted case blocked further submissions. Persistent I/O failure cannot guarantee a durable diagnostic, and the patch correctly makes no such guarantee.
- No automatic diagnostic-table migration occurs. Historical stores are not made compatible by rewriting their approved fingerprint. Existing snapshot/usage interfaces and baseline/DeepSeek workflows passed regression tests. The optional diagnostic extension is only created for explicitly provisioned new synthetic/future stores, not the original stopped session.

As before, these are application controls for a trusted local account, not protection against the owner editing source/database or using their key outside the application. The patch does not claim otherwise.

## Offline verification and actual results

Evidence directory:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostics-independent-20261108`

Python 3.11.15, existing dependencies/model cache. A clean allowlisted environment disabled dotenv and downloads, blanked inherited provider keys, enabled the cached real MiniLM regression, and loaded an audit hook blocking external DNS/socket connections. Fixture keys and all provider responses were synthetic; all registry fault injection was confined to temporary test stores. No real registry was opened through SessionLedger.

Exact executed commands:

```sh
ARTIFACT_DIR=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostics-independent-20261108
python3 "$ARTIFACT_DIR/run_offline.py" full_first -m pytest -q -p no:cacheprovider tests experiments
python3 "$ARTIFACT_DIR/run_offline.py" probes_first -m pytest -q -p no:cacheprovider "$ARTIFACT_DIR/test_review_probes.py"
python3 "$ARTIFACT_DIR/run_offline.py" focused_first -m pytest -q -p no:cacheprovider tests/test_ofox_diagnostics.py tests/test_ofox_demo.py tests/test_ofox_provisioning.py
```

The wrapper launches the worktree's `.venv/bin/python` with those exact pytest arguments. Logs are exclusively created and preserved with matching command/exit-code/timing JSON files. Reproduction must use fresh labels rather than overwrite first-run logs.

| Run | Actual first-run result |
| --- | --- |
| Complete repository and experiment suite | **239 passed**, 57 dependency deprecation warnings, 16.81s. No skips. |
| Independent probes outside the repository | **2 failed, 13 passed**, 5 warnings, 0.79s. Failures reproduce D1 and D2. |
| Focused diagnostic and existing Ofox budget/provisioning tests | **84 passed**, 5 warnings, 6.87s. Includes all 35 new diagnostic and 49 existing Ofox tests. |
| Whitespace validation | `git diff --check` passed. |

The independent probe failures were not retried or modified to get a green result. The focused run is a separate requested test selection, not a successful rerun of the failed probes. Original implementation-run failures/reruns remain in their original evidence directory and are not replaced by these results.

## Preservation and Git hygiene

Before/after review hashes confirm all reviewed source, test and documentation files remained byte-identical. No production file or repository test was changed during this review. Independent probes and logs are outside the repository; this report is the only added repository file.

All tracked historical `experiments/` and `data/` files match the verified base. Retrieval code, frozen prompts/contexts, original fingerprints, scores and approval template are unchanged. The preexisting untracked preflight report was not edited or treated as current consent.

The original stopped registry was only hashed/stat'ed, never queried through a write-capable ledger API. SHA-256 remains `8e48af9ec8958c1f86d0ac86c23902a0458ccd544b4711dfb5c6da9c0e69da23`, and mtime remains `1794121344846265568` ns. See `before.json` and `preservation.json` in the review evidence directory. No actual authorization state was provisioned, reset, relocated or repaired. No real credential or private approval file was read. Generated databases, environments and caches are absent from the proposed patch file list.

## Live-provider uncertainty and successor architecture

The operator's subsequent DNS/TCP/TLS/root-GET success establishes current domain connectivity only. It does not resolve the original EXP11 cause, Chat Completions versus Responses routing, returned model identity, parameter/JSON compatibility, finish behavior, usage completeness or actual charges. This review made no request to establish those facts. Missing Activity/usage is not proof of zero billing.

This diagnostic patch **alone is insufficient for a future live run**, even after D1/D2 are corrected. The old fixed registry is permanently stopped and uses the original approved fingerprint `000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee`. A renamed session or another approval cannot unlock it.

Any successor must be a separately designed/versioned and independently verified controller/journal that recognizes the immutable prior incident at its original canonical path, binds its hash/session/consumed attempts, rejects old approval replay, and prevents duplicate/concurrent successor activation. It must preserve durable reservation-before-dispatch, interruption/fence protections, strict scope/order and the newly authorized absolute ceiling. Do not create an arbitrary replacement registry or modify/move the original file. Fresh explicit consent must bind the reviewed successor source/schema, exact provider/model/route/parameters, permitted cases/order, financial tolerance and stop conditions. Unused historical slots must not become an automatic new allowance. This architecture is a future requirement, not implemented or authorized by this review.

## Publication recommendation

Correct D1 and D2 with targeted synthetic regressions, then rerun the failed independent probes and full suite while preserving these first-run failures. Keep the patch diagnostic-only and exclude the historical local preflight report from publication. No live-recovery feature or approval should be included as an incidental fix.

**CHANGES REQUIRED BEFORE PUBLICATION**
