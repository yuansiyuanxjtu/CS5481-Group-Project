# EXP11 OfoxAI failure postmortem — read-only

8 November 2026, Asia/Hong_Kong. Release `2b2073cdeb1d14eea7635fcd7550632db1fb14e2`; local repository `/Users/yuansiyuan66/Documents/ChatGPT/CS5481 Group Project`. **The root cause remains unknown.** A pinned-route rejection is the leading documentation-driven investigation hypothesis, not an established diagnosis. No new provider request or parameter probe was made.

## 1. Verified observations and preservation

Session `cs5481_ofox_20261108_01` remains **stopped**, with one EXP11 selection attempt in `error`, no generation attempt and one first-result record. The case row says `done`, meaning processing finished; it does not mean acceptance passed. EXP30 and EXP-R07 were not run. Five unused numerical slots are not usable through a stopped session.

- Reserved attempt timestamp: **2026-11-08 07:02:24.023542 UTC**, or **15:02:24.023542 Asia/Hong_Kong**. This is reservation time, not a recorded provider receipt time.
- First result: `llm_error`; error `Experimental model provider request failed.`
- Persisted QA elapsed time: **1.091s**; UI approximately **1.11s**, after wrapper/audit work. No response-receipt or completion timestamp is stored.
- Eight original retrieved chunks match the frozen EXP11 IDs/order. All are from `fsb_20241114_ai_stability`, physical pages 6, 7, 33, 31, 33, 31, 6, 5.
- No accepted answer, claims or citations. `model=null`, `usage={}`, `usage_completeness=partial_or_unknown`.
- Approved source fingerprint remains `000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee` in registry metadata. No provisioning fence exists.

The actual registry was inspected only with SQLite URI `mode=ro` and `PRAGMA query_only=ON`, never `SessionLedger.snapshot()` (which uses a write-capable transaction). Its SHA-256 before inspection was:

`8e48af9ec8958c1f86d0ac86c23902a0458ccd544b4711dfb5c6da9c0e69da23`

Registry size: 45,056 bytes; modification time in nanoseconds: `1794121344846265568`. Final checks compare these values and the file hash again. The original database first-result JSON equals the existing exported first result. Original evidence hashes verify; no timestamps or historical records were rewritten.

Preserved first-run evidence:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-live-exp11-20261108`

Files: `first_result.json`, `audit_readonly.json`, `acceptance_report.md`, `evidence_sha256.json`. Original audit capture was `2026-11-08T07:04:43.810086+00:00`; it is not the request timestamp. The first screenshot remains in the original conversation; its file export was blocked, as recorded in the original report. No new screenshot or reconstruction was substituted.

This postmortem creates only the requested uncommitted Markdown report and separate preservation checks outside Git. No credential or private approval contents were read. No production code, historical evidence, authorization, registry or credentials were changed.

## 2. Exact failure path

Line references refer to the local release named above.

1. `app.py:24–44`: Submit constructs the selected service and calls `answer_question`; setup exceptions use a different UI message. The retained QA result therefore came through the service path.
2. `ofox_demo.py:119–123`: `ledger.begin` claims EXP11 before retrieval. `QAService` retrieves and prepares evidence (`service.py:26–34`), then calls the two-stage client (`service.py:44–51`). The saved evidence confirms retrieval succeeded.
3. `demo.py:54–57` constructs a fresh frozen planner. `planned_generation.py:40–43` begins evidence planning. `selection_adapter.py:71–78` creates the frozen selection messages and calls the bounded underlying chat client.
4. `llm.py:21–25` runs the Ofox override with a total deadline. `ofox_demo.py:86–96` builds the fixed request and calls HTTPX through `GuardedTransport`; this is not the baseline `ChatClient._request` implementation.
5. `ofox_demo.py:24–50` checks URL/model/parameters/question/evidence/prompt. `ledger.reserve` at line 51 commits before the upstream transport factory at line 52 and dispatch call at line 53. The one reservation demonstrates the pre-reservation checks passed. It does **not** prove network bytes reached Ofox: factory/transport failure can happen afterward.
6. If dispatch returns a response, lines 54–62 read and decode it, then require HTTP 200, exact returned model, first choice `finish_reason=stop` and string content. All these failures converge on a false validity result and `LLMError` at lines 63–65.
7. If factory/transport/body reading throws after reservation, lines 67–74 attempt to convert the reserved row to error without releasing its ordinal. `demo_budget.py:232–241` stores only whitelisted aggregate token counters and sets the session stopped on failure.
8. `OfoxChatClient` wraps HTTPX timeout/HTTP errors and budget exceptions as `LLMError` (`ofox_demo.py:102–105`). Other response decoding/content errors use `GenerationError` at lines 99–107.
9. The **exact observed wording** is created by `selection_adapter.py:79–81` when it catches `LLMError`. It drops the original text/exception chain. A different broad exception produces `Unexpected experimental provider failure`; selection-plan parsing produces `invalid_output`, not this message.
10. `service.py:50–51` saves that sanitized message as `llm_error`. `ofox_demo.py:126–135` aggregates any durable usage and saves the first result through `finish`. `demo_budget.py:243–257` records completion, INSERT-only result and stopped state. No final-generation phase is entered.

### Conditions and what the evidence excludes

| Boundary | Possible behavior | Fit to the retained evidence |
| --- | --- | --- |
| Before reservation | Missing key; wrong profile, question, sources, prompt or wire settings; failed case claim | Does not explain a normal committed selection row in error on its own. A missing local key would produce zero reservations. This does not establish that the configured key was valid at Ofox. |
| Reservation commit | Ordinary commit failure before returning the ordinal | Normally leaves no row or an uncertain reserved row, not the observed clean error/result sequence. A durable record is not proof that all I/O was infallible. |
| After reservation, before network | Upstream factory failure subsequently normalized to LLMError | Not distinguishable if it takes the relevant error path. No dispatch-started or response-received marker exists. |
| Transport/body read | DNS, TLS, connect, read/write, disconnect/protocol errors; HTTPX timeout | Compatible when normalized to LLMError and the failure recorder succeeds. No transport class is retained. The ~1.1s latency does not establish routing versus network failure; expiry of the configured 120s total deadline is not supported by that duration. |
| HTTP response rejection | Non-200 status, including routing/authorization/quota/parameter/upstream failure | Fully compatible; HTTP status/error fields are not stored. |
| Envelope validation | Non-JSON body, wrong/missing returned model, wrong/missing choice/finish/content type | Fully compatible: handled inside the guard as LLMError. A null final QA model is not proof that no response carried a model string. |
| Accepted envelope, then content/plan failure | Empty/oversized content, invalid JSON plan, coverage or citation contract failure | Normally produces GenerationError/invalid_output. The exact observed wording and attempt error make these weaker explanations. |
| Audit recording | Failed record/snapshot/finish | A pure persistent audit failure is weakened by the durable error row and saved first result; some after-commit exceptions can still produce a similar terminal state. It cannot be absolutely ruled out from this schema. |

**Known boundary:** planning client failure after a durable selection reservation, with successful final failure/result persistence. **Unknown boundary:** whether a transport was successfully constructed, an HTTP request reached the provider, a response was received, or which validation check failed.

## 3. Ranked hypotheses — investigation priority, not measured probabilities

1. **Pinned OpenAI-channel/Chat routing rejection.** The model page gives OpenAI only Responses while giving Azure both protocols, despite contradictory generic/model examples. A channel-specific rejection is plausible and should be checked first with provider evidence. There is no recorded HTTP status or routing error to prove it.
2. **Other immediate HTTP rejection:** invalid/revoked credential, account/model entitlement, quota/rate limit, unsupported parameter, or gateway/upstream failure. Credential presence is not provider validation. No evidence singles out any of these or establishes a 400/401/403/429/5xx response.
3. **Transport failure before a complete response:** DNS/TLS/direct connectivity, HTTP disconnect or read failure. The adapter deliberately ignores environment proxy configuration. This matters in some networks, but no evidence shows this network requires a proxy; no network probe was performed.
4. **HTTP 200 envelope rejected by strict client checks:** returned model alias/version string, non-stop finish (including reasoning length exhaustion), malformed envelope/content type. Missing usage does not exclude this; usage could be absent, filtered or dropped when schema extraction fails.
5. **Post-reservation local/audit exception.** Possible but less supported by the complete durable failure outcome. A missing key, wrong frozen context, pre-reservation budget rejection or pure selection-JSON contract error is not the leading explanation.

No statistically reliable ranking among the first four is possible without HTTP/provider evidence. Do not label hypothesis 1 a verified root cause or apply an endpoint/provider change merely because it is first in the list.

## 4. Public OfoxAI documentation findings

Checked 8 November 2026, public documentation only:

- The [model-specific page](https://ofox.ai/models/openai/gpt-6-luna) lists `/v1/responses` for `provider.type=openai`, but lists Chat and Responses for `azure_foundry`; its introduction and Python example nevertheless support Chat. This is a real documentation contradiction.
- [GPT family guidance](https://ofox.ai/docs/develop/models/gpt) supports both endpoints for most GPT models and lists Luna on OpenAI. It documents `max_completion_tokens`, low-effort examples/common effort errors and endpoint rejection examples. These generic rules do not resolve the channel-specific table.
- [Routing contract](https://ofox.ai/docs/api/provider-routing) confirms literal `extra_body.provider.type` for Chat; it is equivalent to the provider header. The existing HTTPX JSON nesting is appropriate. The Python-SDK double-nesting warning does not apply to this direct HTTPX implementation. A missing extra routing header is not established as a defect.
- [Provider routing guidance](https://ofox.ai/docs/develop/advanced/provider-routing) says pinning chooses a specific provider and the model page defines per-provider protocols. `provider_type_unavailable` covers an unavailable model/provider mapping; `invalid_provider_type` covers an unknown type. An endpoint rejection could instead use `endpoint_not_supported` or another gateway error. No one code is inferred for this incident.
- [Reasoning guidance](https://ofox.ai/docs/develop/models/gpt/reasoning) says unsupported effort values can return 400 and reasoning consumes the completion budget. A 1,200-token limit can end in empty/length output. This is possible, not demonstrated here.
- [Chat response contract](https://ofox.ai/docs/api/openai/chat-completions) describes the parsed model/choices/usage fields and JSON mode. The adapter's exact model equality, stop-only rule and content checks can reject a returned envelope. Exact Luna JSON/limit/finish behavior remains unverified.
- [Error-handling guidance](https://ofox.ai/docs/develop/guides/error-handling) describes error categories. Its generic retry suggestions are **not authorization to retry this session**.

Thus, explicitly pinning OpenAI on Chat **could** cause a routing/endpoint rejection if the model-specific mapping is authoritative. The generic guidance and example prevent treating that as proven. Keep endpoint, route, fallback, model, reasoning and output settings unchanged pending evidence. No public model-discovery API, protected endpoint or provider status probe was called.

## 5. Existing and missing billing/diagnostic evidence

| Item | Existing local evidence |
| --- | --- |
| Client attempt | One durable selection reservation, state error |
| Provider acceptance | Unknown; reservation is before dispatch |
| HTTP response received/status | Not recorded |
| Provider error type/code | Not recorded |
| Provider request ID | Not recorded; the frozen planner's question-derived request_id is a local question hash, not an Ofox request identifier, and its error event is not persisted by the live callback |
| Returned model/finish reason | Not recorded in the saved failure |
| Prompt/completion/reasoning/cache token counts | No retained counts; aggregate usage is empty |
| Charge/account transaction | None in existing case artifacts or registry |
| Diagnostic log | No live `.log` files in the case artifact directory or local `tmp/`. The retained console output in the execution record shows server startup/shutdown, not HTTP diagnostics. Offline mock logs elsewhere do not diagnose this real request. No general credential/system-log search was attempted. |

No raw HTTP body or header dump was retained. Registry schemas contain no status/request-ID/response-received columns. All original exports were inspected and compared; absence from these bounded evidence locations is not proof that Ofox has no record.

**Missing usage is not zero billing.** Even a failed client operation may have reached an upstream model. The accepted USD 2.00 tolerance is not measured spending. Public GPT guidance now explicitly describes automatic GPT-6 cache-write accounting and cached-token details; this further supports checking actual provider accounting rather than assuming no cache charge merely because no explicit cache operation was requested. No charge can be calculated for this incident.

### Human operator dashboard checklist — no new model requests

1. In the already-authorized Ofox dashboard, inspect historical usage/request records around **07:02:24 UTC / 15:02:24 HKT on 8 November 2026**, allowing several minutes for clock differences. Do not submit a playground request or generate a new key.
2. Match model `openai/gpt-6-luna`, requested route OpenAI and Chat Completions endpoint. Identify the relevant existing key label locally without sharing its secret.
3. Record the matched timestamp, endpoint/channel, HTTP status, whitelisted error type/code, provider request ID and whether upstream inference was accepted. Record absence explicitly if no matching entry exists; absence alone does not prove a client transport failure.
4. Record prompt/completion/reasoning/cache-read/cache-write counts, billed amount/currency, pending/final charge and any reversal. Check billing-settlement delay; do not infer zero from an empty log.
5. Share a redacted export/screenshot containing only those diagnostics. Exclude keys, Authorization/cookie headers, unrelated account data and raw prompt/error dumps. If the dashboard lacks them, ask support to correlate the timestamp/model/endpoint and clarify billing.

No dashboard, credential or protected account endpoint was accessed in this postmortem.

## 6. Observability limitation and smallest proposed future change

This is a verified **diagnostic defect**, not the verified cause of the failed request:

- `ofox_demo.py:55–65` collapses HTTP status, returned model, finish reason and envelope checks into one boolean and generic LLMError.
- `demo_budget.py:234` deliberately keeps only three aggregate usage counters. It has no diagnostic fields.
- `selection_adapter.py:79–81` replaces the underlying LLMError. Its emitted error_type is discarded by `demo.py:43–52`, whose live callback only aggregates successful raw-response usage.
- No exception body or provider response is retained, which prevents secret leakage but also loses safe diagnostic distinctions. Disabling sanitization or logging full HTTP payloads is not an acceptable fix.

**Proposal only; not implemented:** enrich the future versioned attempt record at the existing guarded transport boundary, without changing request construction, routing, retry rules or prompts:

- Preserve ordinal/case/stage and original reservation timestamp; add bounded phase/category and response-receipt timestamp.
- Set `http_response_received=true` as soon as a response object/headers are received, before reading the body; distinguish transport-start intent from proven provider acceptance. Record body-read completion separately if needed.
- Store HTTP status as an integer (100–599) or null; store only finite allowlisted provider error type/code values. For unknown fields, store null plus a safe category, not the raw string or `error.message`.
- Extract at most one documented request-ID field/header, with strict recognized format/length validation. Reject unexpected/control-character values and any value containing the in-memory credential. Do not dump headers or treat a regex alone as secret protection; omit questionable IDs.
- Retain safe enum categories for transport failure, timeout, non-JSON envelope, returned-model mismatch, non-stop finish and audit failure. Do not serialize exception text/repr, keys, Authorization, cookies, raw request payloads or untrusted raw error bodies. Returned model strings should map to approved identity/mismatch categories rather than become arbitrary log content.
- Commit terminal diagnostics and attempt state atomically where possible. Reservation remains consumed before any dispatch. If diagnostic persistence fails, fail closed; do not make a replacement request or erase the uncertain reservation.

Use new-version synthetic tests for routing 400, authentication/quota errors, 5xx, malformed body, length finish, model mismatch, timeout before/after response headers, commit faults and hostile request-ID/error strings that echo a synthetic key. Verify sanitized diagnostics survive the planner's generic message. Do not alter the frozen planner merely to recover exception text.

## 7. Safe recovery proposal — no reset or reuse

The current implementation has **no supported fresh-session recovery after this stop**. Changing a session ID, moving/deleting the database, deleting a fence, replacing approval or manually editing state would bypass the reviewed protection and is not recommended. Five unused slots are not authorization to resume.

1. Keep the original stopped registry at its canonical path and retain its exact hash, session, first result and attempt timestamp. Do not mark it active, rename it, archive it by moving it, migrate its schema or rerun EXP11 under the old approval.
2. Obtain the historical dashboard/support evidence and establish the cause. If the provider confirms a specific unsupported route/parameter or local evidence establishes a transport condition, design only the evidence-supported correction. Do not optimize or probe alternatives speculatively.
3. Because v1 is intentionally terminal, any future session needs a separately reviewed **versioned authorization controller**, not an ad-hoc new registry path. Its fixed versioned control record must recognize the original v1 stopped registry as a tombstone, bind its canonical path/hash/session/consumed-attempt count, and refuse fresh dispatch unless a new explicit successor authorization acknowledges that incident. The original file remains read-only and unchanged; a new controller/append-only successor journal is a new reviewed mechanism, not relocation or reuse of v1.
4. Successor consent must bind the new controller/schema/source hashes, verified cause/correction, exact scope/route/parameters, a newly approved attempt allowance and financial tolerance. Do not automatically replenish six calls, carry forward the unused five, or accept the old approval for a changed source. Renaming IDs alone must never authorize a successor. Crash/replay/concurrent successor creation must fail closed; only one explicit authorized successor may be activated.
5. Test this design entirely offline with mocks, adversarial diagnostics, original security regression cases, legacy-stop recognition, immutable prior-file checks, authorization/fingerprint mismatch, interruption/concurrency and budget/accounting tests. Obtain independent security review and fresh explicit financial/live authorization before any paid call. Implement nothing in this postmortem.
6. A later first-case execution, even if EXP11 again, must be an explicitly approved new experiment under that reviewed successor mechanism, with its own first-result evidence and no automatic progression. Preserve historical DeepSeek results and the failed Ofox record unchanged.

## 8. Provider support and recommended next action

**Provider evidence is needed now; support is conditional.** First have the human inspect the existing dashboard record. If it gives a definitive status/error and billing record, support may be unnecessary. Otherwise ask Ofox support to correlate the recorded timestamp and clarify whether `openai/gpt-6-luna` on the explicitly pinned OpenAI channel accepts Chat Completions with low effort, JSON mode and a 1,200 completion limit; ask which protocol listing is authoritative and whether this failed attempt incurred a charge. Include a request ID only if recovered. Do not send the key, Authorization header, local approval file or raw payload.

The next action is **human retrieval of redacted historical provider diagnostics**, not a new API request, protocol migration or retry. Existing evidence establishes the failed boundary and missing observability, but cannot identify the actual request failure. This report is the only new repository file. No tests requiring execution were run because no implementation change was made; static source tracing and read-only integrity checks suffice for this investigation.

**ROOT CAUSE UNCONFIRMED — PROVIDER EVIDENCE REQUIRED**

## Additional operator evidence — 8 November 2026

Sections 1–8 above preserve the original read-only investigation and refer to the historical release. The statements about no implementation changes describe that earlier investigation. The separately isolated diagnostic patch and its offline verification are documented in `ofox_diagnostic_patch_review.md`; they do not retroactively explain or alter the first EXP11 attempt.

The operator reports successful DNS resolution, TCP connection to api.ofox.ai:443, TLS certificate verification, and an unauthenticated HTTPX GET to https://api.ofox.ai/ returning HTTP 200. That test used AsyncHTTPTransport(retries=0, trust_env=False), certificate verification, no API key and no model request. This establishes current connectivity in the operator test context, not connectivity at the time of EXP11 or Chat Completions/model/parameter compatibility. The historical EXP11 root cause remains unexplained; its stopped registry and original evidence are unchanged. The agent did not repeat this network test.
