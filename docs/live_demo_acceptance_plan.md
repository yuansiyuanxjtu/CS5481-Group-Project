# OfoxAI GPT-6 Luna: controlled live acceptance plan

Date: 8 November 2026, Asia/Hong_Kong. **Offline development authorization only; no paid calls have been made or approved.**

## Release and preservation

Base main: `4bd307bf9c1eee68eb92cb43e821d968206b2c4c`. Work is isolated in the `ofox-demo-guard` managed worktree. The original reports remain in the previous worktree; `docs/final_integration_acceptance.md` is copied byte-identically. The historical DeepSeek baseline and `joint_pairs8` profiles, source data, retrieval algorithms, generation protocol, prompts, manifests, scores and experiment results are unchanged. This new profile is **not a DeepSeek score reproduction or an unseen-test evaluation**.

The existing combined Python 3.11 environment and cached pinned MiniLM are reused; no installs/downloads or real key reads. The preceding offline acceptance verified 155 tests, 30 preflight checks, five PDF checksums and 40 contexts/320 blocks. New adapter/guard verification is recorded below separately.

## Exact configuration and provider compatibility

Select `RAG_DEMO_PROFILE=ofox_joint_pairs8`. Set `OFOX_API_KEY` locally only after approval; never paste a key into chat, logs or a shell command. Existing `LLM_*` DeepSeek settings remain for old profiles and do not redirect the OfoxAI adapter.

| Item | New profile |
| --- | --- |
| URL | `POST https://api.ofox.ai/v1/chat/completions` — no alternate domain |
| Model | `openai/gpt-6-luna` |
| Authentication | Bearer header, kept in memory; never in registry |
| Output | `max_completion_tokens=1200`, non-streaming; JSON `response_format` |
| Reasoning | `reasoning_effort=low`; no DeepSeek `thinking` field |
| Temperature | Omitted because Luna-specific support is not established |
| Deadline | 120 seconds per request including the existing total cancellation deadline |
| Routing | `extra_body.provider.type=openai`, empty `fallback` list |
| Client retries/redirects | Zero retries, no redirects, no environment proxy inheritance |
| Retrieval | Frozen joint_pairs8, enhanced 150/30, eight unique chunks, original five-chunk prefix |
| Generation | Unchanged frozen planning and final prompts; original citation validator |

[OfoxAI Chat Completions](https://ofox.ai/docs/api/openai/chat-completions) documents the endpoint, Bearer authentication and ordinary response/usage shape. [GPT family](https://ofox.ai/docs/develop/models/gpt) documents Chat Completions output limits; [reasoning](https://ofox.ai/docs/develop/models/gpt/reasoning) explains that reasoning uses the completion budget. [Luna model page](https://ofox.ai/models/openai/gpt-6-luna) identifies the exact model and includes a Chat Completions example. [Routing](https://ofox.ai/docs/api/provider-routing) and [fallback](https://ofox.ai/docs/develop/advanced/fallback) describe the explicit routing fields.

**Official-documentation recheck (8 November):** retain Chat Completions. The model introduction and example explicitly support it, and GPT family documentation describes that interface. However, the model page's OpenAI-specific protocol table lists only `/v1/responses`, while Azure lists both. This is an unresolved listing inconsistency, not an observed Chat rejection. We do not migrate endpoints or switch routing. The routing body supplies the provider type; an additional provider-selection header is not required by the routing documentation. Generic Chat documentation covers JSON mode, normal choices/finish reasons and usage. Model-specific acceptance still requires separately authorized live verification.

**Not live-verified:** Luna's acceptance of `low`, JSON mode, output-limit behavior, exact response/model string, reasoning-related truncation, availability and account routing. The adapter accepts only string content, `finish_reason=stop` and the requested returned model; any incompatibility stops the session rather than trying new parameters, endpoints or models. No automatic discovery or fallback call is made. HTTP 401/429/503, timeouts, malformed output and audit failures stop the remaining cases. Provider-internal routing/billing behavior cannot be proven by client mocks.

## Three exact cases

These strings are loaded from `experiments/joint_pairs8/model_inputs40.json`; do not paraphrase them.

### EXP11 — two expected requests

What longer-term changes does the FSB's 2024 executive summary say AI uptake could drive beyond the immediate vulnerabilities it discusses?

Expect a single-document answer covering market structure, macroeconomic conditions and energy use, retaining the source's conditional implications. Inspect the supporting FSB 2024 physical page 6 quote. Require eight original chunks, a supported plan, a separate final model response and validated citations; manually check every clause.

### EXP30 — two expected requests

In the FSB's 2026 multi-agent case example, what does the log record besides final outcomes, and which optional GenAI records does the HKMA's 2026 guidance give as examples for tracing material outputs?

Expect both facts with the FSB physical page 59 and HKMA physical page 5 citations correctly assigned to their claims. Preserve optional/applicability qualifications; an adjacent page or a valid-but-irrelevant quote is insufficient.

### EXP-R07 — one expected request

In the FSB's 2026 investment risk assessment case study, what output does the AI produce, and what is the internal portfolio identifier used in the first assessment?

Expect whole-question refusal: the initial assessment is supported but the internal portfolio identifier is absent. No invented identifier or partial factual answer. The wire guard blocks an unexpected final-generation request for this case before dispatch, and the session stops as a failed acceptance outcome.

EXP28 (missing BIS evidence) and EXP05 (claim/quote scope gap) remain limitations, not successful demo examples. No historical answer is guaranteed to recur with this new provider/model.

## Budget and durable guard

Normal order: EXP11 selection/generation; EXP30 selection/generation; EXP-R07 selection. Expected **five** provider attempts; absolute global ceiling **six**, not a retry allowance. No full40 rerun.

The fixed registry is `~/.local/state/cs5481/ofox-acceptance.sqlite3` under the OS account home (POSIX ignores a changed HOME variable). There is no CLI/env setting for a different registry, output directory or session ledger. `SessionLedger` uses SQLite `BEGIN IMMEDIATE`, full synchronous commits and exclusive initial creation. A question claim is committed before retrieval; each stage reservation is committed before transport construction/dispatch. Both stages, all service instances and reruns share the same database.

Provisioning now persists the exact approved fingerprint and verifies it again before persistence, before activation and after the activation commit. A sibling `.provisioning` fence is exclusively created and flushed before SQLite initialization. All durable database writes and directory syncs occur while that fence blocks every ledger transaction. Removing the fence is the final fallible operation and successful activation point; no sync/write follows it. Any failed/interrupted provisioning leaves the fence in place and cannot be resumed, including from another process or session name. A power failure that loses the final unlink can restore the fence and cause safe unavailability; do not delete it. A fence without a database also locks out other profiles.

Only the three exact question strings, in order, can be claimed. Duplicate/concurrent questions and interrupted running cases cannot resume. Failed/timed-out/uncertain attempts remain consumed. A wrong count/stage, failed audit write, provider error or unexpected answer/refusal stops the session. A clean completed case may be followed manually by the next unstarted case after recreating a service; this never repeats an existing case or resets the counter. There is no automatic resume or recovery loop.

Changing session ID or output filename cannot recreate an existing registry. Consent binds its canonical path and the current application/frozen-input fingerprint (actual question, prompt, method and retrieval bytes, not just manifest labels). The ledger also stores its physical registry path: copied ledgers and symlink aliases are rejected, not treated as new budgets. The registry stores the consent hash, not the approval statement/key. Application submission checks the registry before even a cached baseline service; selecting baseline or historical DeepSeek while the registry exists is blocked, including after terminal completion. First QA results are stored with INSERT-only case IDs, and stage usage remains in the ledger when a later stage fails.

**Threat boundary:** trusted local operator/account, intact local filesystem and this application entry point. OS-account deletion/copy/tampering of the registry, edited Python, another checkout/program using the key, and provider-side hidden retries cannot be prevented by a local Python guard. Do not delete/move the registry to restart. It deliberately has no reset/release command. Windows/filesystem behavior is not newly verified. Baseline and DeepSeek behavior remains unchanged when no acceptance registry exists. An unrelated unguarded script is not an authorized demo entry point.

## Explicit consent procedure — not yet authorized

1. Review the complete local patch and offline results first. Freeze the new source fingerprint and provision only after a separately approved live scope and cost allowance. No live registry was provisioned during development.
2. Copy `docs/ofox_demo_approval.example.json` to a new ignored local approval file. The shipped example is **approved=false**, with null canonical registry/source binding. Never reuse full40 consent or its ledger. Have the user explicitly approve the exact session, canonical registry, source fingerprint, provider/model and six-attempt maximum. Do not auto-fill consent on the user's behalf.
3. Inspect only public fingerprint/path, without reading a key:

```bash
.venv/bin/python -c 'from rag_app.demo_budget import fingerprint, DEFAULT_LEDGER; print(fingerprint()); print(DEFAULT_LEDGER.resolve())'
```

After separately approved consent is supplied, the local-only provisioning entry is:

```bash
.venv/bin/python -m rag_app.ofox_demo --approval-file tmp/NEW_EXPLICIT_APPROVAL.json
```

It exclusively creates the fixed registry and makes **no API request**. Existing/corrupt registries fail closed; do not retry by changing IDs/paths. Only after explicit paid-run approval should the operator put the OfoxAI key in local `.env`, select `ofox_joint_pairs8`, verify the copied index/cache settings, restart the normal Streamlit app and submit each exact question once. Keep all other provider-capable processes stopped. Do not run pytest with real credentials.

## Cost estimate and billing limits

Rates rechecked on the [official Luna model page](https://ofox.ai/models/openai/gpt-6-luna), 8 November 2026. USD per million tokens:

| Input context per request | Uncached input | Output | Cache read | Cache write |
| --- | ---: | ---: | ---: | ---: |
| ≤272,000 | $0.10 | $0.50 | $0.01 | $0.125 |
| >272,000 | $0.20 | $0.75 | $0.02 | $0.25 |

Apply the rate for each request's context, not the combined session input. Formula: sum `(uncached_input*input_rate + cached_read*read_rate + cache_write*write_rate + completion*output_rate)/1,000,000`, where input categories are disjoint under this estimate. Provider-specific cache-write accounting is not established; verify it before live approval.

All rows assume **1,200 output tokens per request including reasoning**, not 1,200 visible tokens plus extra reasoning. Expected flow uses five calls; six is the absolute request ceiling, not permission to retry. No tools/search are requested. No provider token counts have been measured.

| Scenario | Max calls | Input tokens per call | Total output incl. reasoning | Cache assumptions | Applied rates input/output | Estimate |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| Expected-flow working estimate | 5 | 100,000 | 6,000 | None | $0.10/$0.50 | $0.0530 |
| Six-call working estimate | 6 | 100,000 | 7,200 | None | $0.10/$0.50 | $0.0636 |
| Low-tier boundary | 6 | 272,000 | 7,200 | None | $0.10/$0.50 | $0.1668 |
| First high-tier context | 6 | 272,001 | 7,200 | None | $0.20/$0.75 | $0.3318012 |
| Coarse full-context stress | 6 | 1,048,576 | 7,200 | None | $0.20/$0.75 | **$1.2636912** |
| Low-tier illustrative all-cache-read | 6 | 100,000 | 7,200 | All input read, none written | $0.01/$0.50 | $0.0096 |
| High-tier illustrative all-cache-read | 6 | 1,048,576 | 7,200 | All input read, none written | $0.02/$0.75 | $0.13122912 |
| Conditional low-tier cache-write stress | 6 | 100,000 | 7,200 | All input written, none read/uncached | $0.125/$0.50 | $0.0786 |
| Conditional high-tier cache-write stress | 6 | 1,048,576 | 7,200 | All input written, none read/uncached | $0.25/$0.75 | **$1.578264** |

The last two rows illustrate the listed cache-write rates replacing ordinary input charges; whether this route applies those rates automatically or with other accounting is unverified. The adapter requests no explicit cache writes. Do not assume cache savings or treat these rows as a proven upper bound. The full-context assumption is deliberately coarse and does not assert that a full input window plus output will be accepted.

**Correction:** the earlier ~$0.633 full-context estimate incorrectly used the low-context rates; uncached high-context pricing gives ~$1.264, exceeding the old $1 proposal. The user selected **$1.50 proposed allowance for later authorization**, explicitly **not permission to spend**. Preserve that choice as a proposal. It covers the uncached scenario but not the conditional $1.578264 cache-write stress. Resolve actual cache billing and input limits/account controls before paid approval; if that stress applies, reduce the approved scope or obtain a new allowance decision. No higher allowance has been approved automatically.

These are estimates, **not guaranteed billing ceilings**. Request-count protection does not impose a dollar limit or control provider accounting, other account spend, uncertain failed requests or future prices. Unknown usage is not zero. Missing reliable rates/account controls blocks live approval. A 1,200-token reasoning budget may truncate output; preserve the first failure and stop, without changing parameters or retrying.

## Evidence and stop conditions

The registry records session consent/source binding, exclusive cases, reserved attempt ordinals/stages/UTC times, sanitized response status and whitelisted reported token counts. It saves each first QA answer/refusal/error without credentials or HTTP headers. Returned QA data includes new-profile/origin labels, per-stage attempts and usage completeness; raw registry stage usage supplements incomplete provider/QA totals. Use `SessionLedger(DEFAULT_LEDGER).snapshot()` and `.first_result(case_id)` for readout; never call a model again merely to recover an export.

For every case save a new QA export/screenshot, exact question, commit/source fingerprint, UTC start/end and elapsed time, profile/provider/requested and returned model, evidence IDs/chunk IDs/document URLs/physical pages, validator outcome, error category and usage completeness. Do not append these results to frozen evaluations or describe them as unseen-test accuracy. Partial stage usage is retained in this new adapter even if generation fails; this does not retroactively fix historical outputs.

Manual review:

- [ ] Exact question, source/configuration fingerprints, eight distinct chunks and five-chunk prefix.
- [ ] Expected stage count/order; all uncertain/failed reservations accounted for.
- [ ] Both requested facts supported, or whole-question refusal; no invented identifier.
- [ ] Every substantive clause supported by its own exact quote, including qualifications.
- [ ] Correct document/version, official URL and physical PDF page; unknown status not called current.
- [ ] JSON/citation validation and human semantic judgment recorded separately.
- [ ] First answer/failure retained, no retry/resampling; usage completeness explicit.
- [ ] Reviewer/time/verdict/reasons and screenshots/exports recorded without secrets.

Stop before dispatch on wrong configuration/question/evidence/prompt, duplicate/out-of-order/concurrent/restarted running case, source/consent mismatch, missing key/approval or failed ledger I/O. Stop after any provider/audit/output/citation failure, unexpected supported/refused case, unexplained model change or budget issue. Preserve remaining cases as not_run. A model-specific parameter error is a recorded failure, not permission to probe alternatives.

## Offline verification record

Final full suite: **185 passed, 57 existing dependency warnings, zero skips** (10.55 seconds pytest time), including the original 155 tests and **30 new adapter/guard tests**. External networking was blocked by an audit hook; real credential-like environment variables were removed and dotenv loading disabled. No real keys were read.

Coverage includes URL/model/parameter envelope, planning/final citations, whole-question refusal, 401/429/503, network timeout/malformed response, retained partial usage, shared stage budget, seventh-attempt rejection before transport construction, restart uncertainty, exact-case/order/duplicate protection, multi-thread and four-process contention, source/root/copy/symlink binding, audit write failure and cached baseline-profile bypass prevention. Existing baseline/DeepSeek, A/B/C and historical authorization tests pass unchanged.

Preserved first failures/reruns:

- `targeted_first.log`: 14 passed, 2 failed because fault injection patched a separate ledger instance rather than the service's instance. Corrected the test target; `targeted_second.log`: 24 passed before subsequent coverage additions.
- `full_first.log`: 169 passed, 13 failed. Existing historical authorization tests could not create worktree `tmp/` under the sandbox. The permitted-write rerun `full_second.log` passed 182 tests.
- After stronger wire-budget/refusal assertions, `full_final.log`: 183 passed. After registry relocation protection, `full_path_binding.log`: 184 passed. Binding the actual frozen input bytes as well as code and adding its runtime regression produced the final `full_frozen_binding.log`: **185 passed**. These reruns followed explicit code/test improvements or environment diagnosis; no failed run was hidden.
- Historical controller preflight: **30 checks passed**, no real requests/credentials.
- Frozen retrieval replay: **40 contexts / 320 evidence blocks matched**, maximum distance delta `2.72e-07`.
- Real local-index OfoxAI adapter probe: **five synthetic dispatches**, EXP11 answered with FSB page 6, EXP30 answered with HKMA page 5 and FSB page 59, EXP-R07 refused. Token usage 20/20/10 is synthetic, not measured Luna billing or semantic accuracy.

Artifacts and exact command/exit records are outside Git:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-guard-20261108`

Run from this worktree using the existing combined environment:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHON_DOTENV_DISABLED=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 RAG_TEST_REAL_MODEL=1 \
  .venv/bin/python -m pytest -q -p no:cacheprovider tests experiments
```

For the recorded external-network guard and credential stripping, use `run_offline.py` from that artifact directory with a **fresh** output label. For example `python3 /ABSOLUTE/ARTIFACTS/run_offline.py NEW_LABEL -m pytest -q -p no:cacheprovider tests experiments`. A managed-worktree sandbox may require permission to create synthetic tmp fixtures; this does not authorize provider traffic. No dependency/model installation was required. No GitHub CI claim is made.

## Targeted security-fix verification (supersedes earlier readiness)

The earlier 185-test results above remain historical evidence for the original patch. The original independent report `docs/ofox_patch_review.md` is preserved unchanged. The two subsequent provisioning defects and corrected cost assumptions are addressed in [ofox_security_fix_verification.md](ofox_security_fix_verification.md).

Patched version: **204 repository tests passed**, **49 focused tests passed**, **7 independent boundary probes passed**, **30 offline preflight checks passed**, and **40 contexts / 320 frozen blocks matched**. The original two attacks were reproduced first and retained as two failures, each with one unexpected synthetic dispatch; the patch blocks both before any dispatch. All current verification used synthetic consent/credentials and blocked external networking. No live registry or real approval was created.

## Readiness

The implementation is available for local review and mock testing, not authorization to spend. Explicit paid consent, local key setup, current pricing confirmation and the acknowledged live-compatibility uncertainties remain prerequisites. No real key was read/created/modified, no real registry/approval was provisioned, and no paid API request, commit, push, merge or tag was made.

**READY FOR FINAL INDEPENDENT REVIEW** — targeted fixes and offline verification complete. Provider-specific compatibility and cache billing remain documented live-authorization prerequisites; no paid execution authorized.
