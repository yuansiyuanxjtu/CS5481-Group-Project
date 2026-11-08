# OfoxAI diagnostic patch — offline review

8 November 2026. **READY FOR INDEPENDENT REVIEW; NOT AUTHORIZED FOR LIVE EXECUTION.**

Implementation is isolated on `codex/ofox-failure-diagnostics` in `/Users/yuansiyuan66/.codex/worktrees/ofox-demo-guard/cs5481-final-acceptance-20261108`, based on release `2b2073cdeb1d14eea7635fcd7550632db1fb14e2`. No commit, push, merge, provider request or new live authorization was performed. The operator's checkout and original reports remain unchanged.

## Scope and exact files

| File | Change |
| --- | --- |
| `src/rag_app/ofox_demo.py` | Collect sanitized diagnostics at reservation, factory, transport, body, envelope and audit boundaries; retain them outside the frozen planner's generic errors and in the first QA result. |
| `src/rag_app/ofox_diagnostics.py` | New fixed-schema sanitizer, bounded enum fields, exception-class classification and correlation-ID hashing. |
| `src/rag_app/demo_budget.py` | Optional diagnostic argument to terminal attempt recording; atomic INSERT-only diagnostic persistence; bounded first-result diagnostics and an accessor. New stores alone receive the extension table during provisioning. |
| `tests/test_ofox_diagnostics.py` | 35 offline regression cases using synthetic consent, temporary SQLite stores and MockTransport. |
| `tests/conftest.py` | Isolate tests from the operator's fixed registry by redirecting the default to a temporary test path. Existing tests can still set their own temporary paths. |
| `docs/ofox_exp11_failure_postmortem.md` | Copy the original report into this isolated worktree and append the newly reported operator connectivity evidence, with historical-context caveats. |
| `docs/ofox_diagnostic_patch_review.md` | This uncommitted review and reproduction report. |

The preexisting untracked `docs/ofox_live_preflight.md` was preserved and is not part of this patch. No dependency, application UI, retrieval implementation, source document, prompt, score, frozen manifest, approval template or experiment record changed.

## New operator evidence and historical uncertainty

The operator reports successful DNS, TCP to api.ofox.ai:443, verified TLS, and HTTP 200 from an unauthenticated GET to `https://api.ofox.ai/`, using zero retries and `trust_env=False`. These observations establish current operator connectivity to the domain. They do not establish historical connectivity, Chat Completions routing, model/parameter support, receipt of the original request, or its billing. The agent did not repeat these network checks.

The original EXP11 failure remains unexplained. Its approximately 1.11-second selection-stage failure, missing provider Activity entry, and generic planner error cannot identify the original HTTP status or network error. Root-endpoint HTTP 200 is not model API compatibility evidence. Provider-side historical correlation remains useful; any support request must omit keys, headers and payloads.

## Diagnostic contract

Every record is rebuilt from an exact schema at collection and persistence boundaries:

- `schema_version=1`; consumed `attempt_ordinal` (1–6, or null before reservation); `stage` (selection/generation/unknown).
- UTC start and terminal-observation timestamps, `failure_stage`, and bounded `category`.
- Boolean `transport_constructed`, `dispatch_started`, `http_response_received`, `body_read_complete`.
- Integer `http_status` when headers are available.
- Exact allowlisted `provider_error_type` / `provider_error_code`; unknown values are omitted, not truncated or copied.
- Allowlisted `finish_reason`, or `other` for an unexpected value.
- `request_id_sha256`: digest of a recognized, bounded request-ID header, never its raw value. Headers containing the configured synthetic/live key are rejected before hashing. No headers themselves are retained.

Categories distinguish DNS, TLS, generic connect, proxy, timeout, other network failure, HTTP rejection, invalid JSON/schema, model mismatch, non-stop finish, invalid content, budget failure and audit failure. DNS/TLS detection uses exception classes in a bounded cause/context chain, never exception messages. If HTTPX drops the original cause, the diagnostic remains a generic connection failure; it does not guess from text. A total request cancellation caused by the existing deadline is classified as timeout.

`dispatch_started` means the adapter handed the request to the upstream transport. It is **not** proof of DNS resolution, a TCP connection, bytes sent, provider receipt or billing. A received response's status remains available even if body reading fails. Non-200 status takes precedence over invalid JSON in an error body. Expected model identity remains the fixed existing configuration; an untrusted returned model string is not copied into diagnostics.

Terminal diagnostics are INSERT-only in `attempt_diagnostics_v1`, atomically with the attempt's terminal state and token-counter update. The first result contains at most six sanitized summaries, and the client retains at most six in memory. The diagnostic accessor returns at most six rows. Existing attempt snapshots and usage-counter contracts remain compatible. No diagnostic file or external telemetry sink is added.

## Mocked examples and coverage

| Synthetic failure | Retained diagnosis |
| --- | --- |
| HTTP 400/401/403/429/503 with structured error | `http_error`, actual status, response/body flags, only known error type/code and request-ID digest. |
| HTTP 502 with non-JSON private body | `http_error`, 502; no raw body. |
| HTTPX ConnectError caused by gaierror / SSLCertVerificationError | `dns_failure` / `tls_failure`, transport handoff, no response status. |
| Connect timeout, read timeout after headers, connection reset, proxy failure | Respective bounded category; status retained after headers; one consumed attempt. |
| Invalid JSON or malformed choices/message | `invalid_json` or `invalid_schema`, HTTP 200. |
| Unexpected model | `model_mismatch`; raw model string absent. |
| `length` or object-valued finish reason | `non_stop_finish`; bounded `length` or `other`. |
| Empty content | `invalid_content`; existing invalid-output handling retained. |
| Diagnostic INSERT failure | `audit_failure` in memory; transaction rolls back terminal update, leaving the already durable reservation consumed and replay blocked. |
| First-result persistence failure | Safe audit diagnostic returned in memory; terminal attempt records remain durable and interrupted case blocks continuation. |

Tests also cover transport-factory and reservation failures, malformed provider error objects, secret-bearing headers, unknown error strings, fixed-schema redaction, separate selection/generation records, missing usage remaining unknown, first-record immutability, and absence of automatic schema migration. Error messages, API keys, Authorization headers, proxy password sentinels and raw request IDs are absent from persisted diagnostics and returned test results.

## Tests and exact commands

All invocations used Python 3.11.15 with cached model files, offline Hugging Face settings, dotenv disabled, a clean allowlisted environment and empty inherited provider keys. Test fixtures install synthetic keys only. An interpreter audit hook blocked external DNS/socket connections, including subprocesses. No authenticated request or unauthenticated connectivity probe was sent.

Evidence directory:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostic-patch-20261108`

Exact commands executed, from the isolated worktree (the wrapper records argv, exit code and duration in matching JSON files and uses exclusive log creation):

```sh
ARTIFACT_DIR=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-diagnostic-patch-20261108
python3 "$ARTIFACT_DIR/run_offline.py" targeted_first -m pytest -q -p no:cacheprovider tests/test_ofox_diagnostics.py tests/test_ofox_demo.py tests/test_ofox_provisioning.py
python3 "$ARTIFACT_DIR/run_offline.py" targeted_second -m pytest -q -p no:cacheprovider tests/test_ofox_diagnostics.py tests/test_ofox_demo.py tests/test_ofox_provisioning.py
python3 "$ARTIFACT_DIR/run_offline.py" full_first -m pytest -q -p no:cacheprovider tests experiments
python3 "$ARTIFACT_DIR/run_offline.py" full_second -m pytest -q -p no:cacheprovider tests experiments
```

To reproduce without overwriting first-run evidence, use a fresh log label, such as `reproduce_full`, with the last command's arguments. The wrapper's underlying full command is `.venv/bin/python -m pytest -q -p no:cacheprovider tests experiments`; both configured repository tests and additional experiment tests are included.

| Invocation | Actual result |
| --- | --- |
| targeted_first | **2 failed, 79 passed** in 6.39s. Two new fault-injection tests patched the fixture ledger rather than the service's separate instance of the same temporary store. No production failure was hidden. |
| targeted_second | **81 passed** in 5.81s after correcting those test targets. |
| full_first | **1 failed, 238 passed** in 15.38s. An added timeout test requested 0.05s, below the existing Settings minimum; it failed before dispatch. |
| full_second | **239 passed**, 57 dependency deprecation warnings, in 15.65s after using the supported one-second timeout. Includes all 204 preexisting cases and all 35 new cases. No skips. |

Initial failures and subsequent runs remain in separate logs. `git diff --check` passed. Mocked failure verification does not establish actual Ofox compatibility or validate any real response.

## Security and preservation

The existing provider/endpoint, model, profile, wire parameters, frozen messages, source-binding checks, fixed canonical registry, provisioning fence, case order, duplicate protection and absolute six-attempt ceiling are unchanged. Transport retries remain zero, environment proxy use remains disabled, TLS verification remains enabled and redirects remain disabled. No fallback, parameter probing or recovery was added.

The extension table is created only by the existing explicit new-store provisioning path; no existing registry is opened for migration or repair. This implementation does not enable a successor acceptance session. The fixed path already contains a stopped session, so ordinary provisioning must still refuse it. The old approval cannot authorize this changed source.

Historical approved source fingerprint, preserved in the original evidence:

`000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee`

Current uncommitted patch source fingerprint:

`4de7fa9c60af2d02efb79d7e6d678ab33b82e2ca696d7b7000e51496d19b948c`

The change is intentional and requires fresh independent review; no historical approval or fingerprint was rewritten to match it.

Preservation checks compared all preexisting tracked files with their initial hashes. Only `ofox_demo.py`, `demo_budget.py` and `tests/conftest.py` changed among those files. All tracked experiment/data files, original operator reports and the preexisting worktree preflight report remain byte-identical.

The original registry remains at `/Users/yuansiyuan66/.local/state/cs5481/ofox-acceptance.sqlite3`. It was only hashed/stat'ed during this patch verification, never opened through SessionLedger. SHA-256 and modification time remained unchanged:

- SHA-256: `8e48af9ec8958c1f86d0ac86c23902a0458ccd544b4711dfb5c6da9c0e69da23`
- Modification time (ns): `1794121344846265568`

See `preservation_before.json` and `preservation_after.json` in the evidence directory. No real `.env`, key, approval content or Authorization header was read or displayed.

## Limitations and next step

A process crash before terminal recording leaves only the existing durable reservation, not a terminal diagnostic. An audit write failure cannot guarantee durable diagnostics; a safe in-memory summary is returned when possible, while the consumed reservation and interrupted case remain blocked. Diagnostics do not guarantee provider receipt, zero billing, raw request-ID recovery, or dollar-denominated cost enforcement. No external log retention system or live monitoring was introduced.

For future use, first independently review this patch and establish the provider's historical error evidence where possible. Because the original fixed registry is permanently stopped, a future live run requires a separately designed/reviewed versioned successor authorization mechanism recognizing the immutable prior incident, plus fresh explicit consent binding the then-current fingerprint, scope, model, ceiling and financial tolerance. That mechanism is outside this diagnostic patch. Do not relocate/delete/reset the old registry, reuse its approval, or treat its unused slots as authorization.

After those prerequisites, a newly authorized application path would attach these summaries to its new attempt audit and first result; a failure would stop immediately, with no retry or automatic continuation. No new session or live approval has been created here.
