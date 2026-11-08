# Final OfoxAI security and release-readiness review

Review date: 8 November 2026, Asia/Hong_Kong. Scope: the complete uncommitted OfoxAI patch, including provisioning remediation. No production code or historical evidence was edited during this review. Findings are based on source inspection, new attack probes and fresh local runs, not merely the previous verification report.

## 1. Exact reviewed state

- Base/HEAD: `4bd307bf9c1eee68eb92cb43e821d968206b2c4c`, detached, in `/Users/yuansiyuan66/.codex/worktrees/ofox-demo-guard/cs5481-final-acceptance-20261108`.
- Application/frozen-input fingerprint: `000266d6a0b31447c9bc47c72cfbbf8712ef8f70945877a528c473ae54952eee`. Independently recomputed and equal to the remediation artifact's fingerprint. This is an identity check, not a real authorization.
- Initial state: five modified tracked files, nine untracked patch/report files; nothing staged. No remote is configured in this isolated checkout. No claim about current GitHub branch/CI state is made.
- All 172 initial tracked/nonignored file hashes were captured. End-of-review checks require every initial file to remain byte-identical. The only new repository file from this review is this report. External probes, logs and copied databases are outside the worktree.

### Complete changed-file summary relative to base

| Files | Purpose |
| --- | --- |
| `.env.example` | Blank Ofox key placeholder and opt-in profile explanation |
| `.gitignore` | Ignore a `.venv` symlink as well as an environment directory |
| `README.md` | Link the separate Ofox acceptance workflow and authorization restrictions |
| `app.py` | Select the Ofox key for that profile and enforce the registry lock on cached services |
| `src/rag_app/demo.py` | Opt-in dispatcher; existing baseline/DeepSeek implementations retained |
| `src/rag_app/demo_budget.py` | Canonical registry, approval/source binding, fenced provisioning, atomic case/stage reservations and audit/results |
| `src/rag_app/ofox_demo.py` | Pinned provider adapter, guarded wire envelope, two-stage orchestration and partial-usage retention |
| `tests/test_ofox_demo.py` | 30 adapter/application/guard cases |
| `tests/test_ofox_provisioning.py` | 19 provisioning fault/restart/concurrency cases |
| `docs/live_demo_acceptance_plan.md` | Exact questions, configuration, consent procedure, costs and stop conditions |
| `docs/ofox_demo_approval.example.json` | Inert template: approved=false, null source/path/statement |
| `docs/final_integration_acceptance.md` | Preserved earlier integration report |
| `docs/ofox_patch_review.md` | Preserved original independent findings and evidence |
| `docs/ofox_security_fix_verification.md` | Remediation verification and historical failure record |
| `docs/ofox_final_security_review.md` | This review, added after verification |

## 2. Security findings

**No remaining publication-blocking defect was reproduced within the documented trusted-account/filesystem boundary. Both previously reproducible P2 defects are fixed.**

| Control | Independent finding |
| --- | --- |
| Approved fingerprint | `demo_budget.py:117` captures the approved value; lines 145–146 persist that value. Checks before persistence/activation and after the activation commit reject changed sources. Runtime transactions recheck binding at lines 182–184. No freshly observed hash replaces approval. |
| Failed provisioning | Fence creation precedes database initialization. Every transaction rejects it before opening and after acquiring its lock (`demo_budget.py:173–179`). Commit/sync/source faults leave authorization unusable after reopen. SQL active alone grants nothing. |
| Successful activation boundary | Final fence unlink (`demo_budget.py:160`) is the success linearization point; no later fallible sync/write follows. Power loss can restore the fence and block use. A process killed after successful release may leave a valid authorization even if the caller never sees the return; this is an uncertain completed operation, not a reset allowance. Never automatically retry provisioning. |
| Shared budget | `BEGIN IMMEDIATE`, synchronous FULL commits and unique case/stage records serialize reservation before transport creation. Twelve processes contending for the sixth ledger slot produced one winner and eleven rejections. No seventh transport was constructed. |
| Policy scope | Only exact EXP11, EXP30 and EXP-R07 questions, in order. Five normal calls: 2+2+1. Six is a ledger ceiling, not a promised sixth wire call: the transport additionally rejects R07 final generation. Ledger stress tests deliberately exercise slot six below that stricter wire policy. |
| Replay/reset resistance | Existing tests pass for duplicate/interrupted questions, new instances/processes, renamed sessions, canonical path/copy/symlink relocation, and profile switching even through cached Streamlit services. No environment path/session override exists in the application entry point. |
| Failure consumption | Timeout, malformed response, wrong returned model and reasoning-length termination each consumed one reservation, stopped the session and caused no second dispatch. Restart does not clear uncertain reservations. |
| Audit/secrets | Authorization header and provider bodies are not serialized. Token usage uses a three-counter whitelist; synthetic secret/header fields were excluded from the SQLite bytes. Error messages are bounded/static. QA first-result rows are INSERT-only. The consent statement is hashed, not stored verbatim. |

### Fresh attack reproduction

A separately written probe loads the archived vulnerable budget module from the previous artifacts and points only its resource root to current public project inputs. It does not replace any repository file or create real consent. Both attack forms produced **one unexpected synthetic dispatch** under that archived implementation. Under current code, the same source-mutation and fsync-failure/reopen paths produced **zero**. The patched tests try reopening after rejection, including restored approved sources, rather than accepting the exception alone as sufficient evidence.

Further fresh probes inject errors after successful initialize/activate commits, test twelve-process reservation contention and scan synthetic usage audit storage. Four additional response-boundary probes test length exhaustion, wrong model, malformed JSON and uncertain timeout. All pass.

### Trust boundaries

This is an operator-controlled local demonstration guard, not an adversarial-user authorization service. The approval JSON is not cryptographically signed. The trusted account can edit code, fabricate consent, restore a same-path database backup, delete the fence/registry, change OS accounts or run another provider client. Those actions are outside the guard. Raw provider/internal billing retries and account-wide spending are also outside it. Source files must remain stable during execution; checks do not attest already-loaded Python against malicious filesystem races. Failed initialization has no recovery/reset path and can permanently sacrifice availability. Process/fault tests are not physical power-loss validation; Windows/filesystem portability is unverified.

## 3. Provider compatibility

Public Ofox documentation was read; no model/account API or authenticated provider request was made.

- The [GPT family documentation](https://ofox.ai/docs/develop/models/gpt) documents Chat Completions, `max_completion_tokens` and `reasoning_effort`. Its provider table includes Luna on OpenAI. Retaining Chat is appropriate.
- The [model page](https://ofox.ai/models/openai/gpt-6-luna) introduction/example supports Chat, but its OpenAI-specific protocol list shows only Responses; Azure lists both. This remains an unresolved documentation inconsistency, not a demonstrated rejection.
- [Routing](https://ofox.ai/docs/api/provider-routing) explicitly supports literal `extra_body.provider.type` in Chat JSON, equivalent to the routing header. The actual HTTPX body correctly includes that literal nesting; no extra header is necessary. `provider.type=openai` is pinned.
- [Fallback documentation](https://ofox.ai/docs/develop/advanced/fallback) defines the backup-model array. The empty list, fixed endpoint/model, zero client retries, disabled redirects and disabled environment proxies introduce no client model/endpoint fallback. Returned model identity is checked; client mocks cannot prove upstream channel honesty.
- [Chat reference](https://ofox.ai/docs/api/openai/chat-completions) supports JSON mode and the parsed choices/content/finish/usage fields. Only status 200, exact model, string content and `finish_reason=stop` are accepted. Empty/oversized/malformed content is rejected downstream, with original citation validation still active.
- [Reasoning documentation](https://ofox.ai/docs/develop/models/gpt/reasoning) says reasoning consumes output tokens and can reject unsupported effort values. **Yes, the 1,200-token completion budget could be exhausted by internal reasoning before usable JSON.** A synthetic all-reasoning/length response was rejected and consumed its reservation; the service does not increase the limit or retry. Nested reasoning counts are not separately persisted; completion totals include them when reported.
- HTTP timeout and inherited asyncio total deadline are 120 seconds **per stage**, potentially two stages per supported answer. This bounds client waiting, not provider execution/billing after cancellation.

Exact-route acceptance of low effort, JSON mode, output limits, returned model spelling, availability, cache billing and provider behavior still require separately authorized live testing. Temperature/thinking/tools are omitted. No protocol migration or parameter experimentation is authorized by this review.

## 4. Application and provenance compatibility

The profile is opt-in (`RAG_DEMO_PROFILE=ofox_joint_pairs8`); baseline remains the default. Without an acceptance registry/fence, old baseline and DeepSeek code paths remain available and pass regression tests. Once provisioned, deliberate profile locking applies even after completion; switching profiles is not a recovery option.

The adapter uses the unchanged `JointCandidateRetriever`, eight original chunks and frozen two-stage planner/prompts. Citation validation remains in `QAService`; document IDs, physical pages, URLs and quotes pass through the existing contract. Partial first-stage usage and first QA failure records survive a later provider failure. Storage failure/interruption may prevent the final QA result from being written, but cannot free consumed attempts; preserve surviving audit state and never redispatch to recover an export. Raw provider outputs/headers are intentionally not archived by this adapter.

All **87 tracked files under experiments/data/config/src, except the already-modified demo dispatcher**, match base byte-for-byte. Frozen prompts, manifests, retrieval algorithms, scores and historical evidence were not regenerated. Fresh replay verified 40 contexts and 320 blocks against a database copy, max distance delta `2.72e-07`.

Real-index mock integration produced five dispatches: EXP11 answered with FSB 2024 physical page 6; EXP30 answered with HKMA 2026 page 5 and FSB 2026 page 59; EXP-R07 refused. Retrieved chunk IDs matched frozen records. Mock answers/usage are not Luna performance or cost measurements. Exact quotes prove provenance, not semantic entailment; human claim/quote review remains necessary.

## 5. Independent verification commands/results

Run from the reviewed worktree. `ART` is the new review artifact directory:

```bash
ART=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-final-security-review-20261108
python3 "$ART/run_offline.py" full_first -m pytest -q -p no:cacheprovider tests experiments
python3 "$ART/run_offline.py" security_first -m pytest -q -p no:cacheprovider \
  tests/test_ofox_demo.py tests/test_ofox_provisioning.py "$ART/test_prior_attacks.py"
python3 "$ART/run_offline.py" fresh_attacks_first -m pytest -q -s -p no:cacheprovider \
  "$ART/test_fresh_review.py"
python3 "$ART/run_offline.py" response_boundaries_first -m pytest -q -p no:cacheprovider \
  "$ART/test_fresh_review.py" -k response_rejection
python3 "$ART/run_offline.py" preflight_first experiments/generative40/preflight_controller80.py \
  --runtime experiments/generative40/runtime --app-src src --output "$ART/preflight"
python3 "$ART/run_offline.py" replay_first experiments/joint_pairs8/verify_replay.py \
  --experiment-dir "$ART/index_copy" --cache-dir .cache/huggingface/hub
python3 "$ART/run_offline.py" real_index_first "$ART/independent_real_index.py"
```

Runner uses project Python 3.11, a small environment whitelist with blank provider keys, dotenv disabled, cached/offline MiniLM and an external-network/DNS-blocking audit hook. It does not load a real key. Logs are exclusively created; use fresh labels/output directories for reproduction. Preflight and real-index service use synthetic credentials/transports only. Databases are copied, never rebuilt or deleted. Existing resources required no installs/downloads.

| Run | Actual first-run result |
| --- | --- |
| Full tests/experiments | **204 passed**, 57 dependency warnings, no skips; 14.17s pytest, exit 0 |
| Ofox security tests plus prior probes | **56 passed**, 5 dependency warnings; 7.26s, exit 0 |
| Fresh independent probes | **8 passed**, 0.41s, exit 0; archived defects deliberately asserted as vulnerable, current code blocked |
| Added response probes | **4 passed, 8 deselected**, 0.20s, exit 0 |
| Historical offline preflight | **30 checks passed**, exit 0; zero real upstream requests/key reads |
| Frozen retrieval replay | **40 contexts / 320 blocks matched**, exit 0 |
| Real-index Ofox integration | **5 mock dispatches**, expected answers/refusal and citation pages, exit 0 |

The first fresh probe file contained eight cases; four response cases were added afterward. To reproduce that first eight against the final file, append `-k 'not response_rejection'`. Counts overlap across suite/security runs and must not be summed as unique repository tests. No test failed or was silently retried in this review. Original negative-reproduction failures and earlier author's environment/test errors remain in their preserved reports.

One administrative `git check-ignore` invocation failed because it named a child below the symlinked model cache. Rechecking the `.cache` parent and other representative paths succeeded. This was a Git path-inspection limitation, not an application/test failure. Detailed commands/exits, source and protected-file hashes, cost recalculation and original probe sources are retained under ART. These are **local results, not GitHub CI**. Supplemental external probes are local artifacts; the 49 Ofox repository tests and full suite are shipped reproducible tests.

## 6. Costs and authorization

Only EXP11, EXP30 and EXP-R07 are planned; expected attempts are five, with an absolute shared ledger ceiling of six. The user selected **$1.50 as a proposal for later authorization**, not an approved allowance or permission to spend. The approval template remains inert. No live registry was provisioned.

Independent decimal recalculation matched every cost row in the acceptance plan. Published model-page tiers are ≤272,000 input tokens at $0.10/M input and $0.50/M output, and >272,000 at $0.20/M and $0.75/M. Six calls of 100,000 input tokens plus 7,200 total completion tokens estimate $0.0636. Six coarse full-context inputs of 1,048,576 tokens estimate **$1.2636912** uncached. Conditional cache-write replacement-rate stress gives **$1.578264**, already above the proposal. Cache-read cases and reasoning within completion totals are included. No cache savings are assumed for uncached estimates. [Official model pricing](https://ofox.ai/models/openai/gpt-6-luna).

**There is no confidently established worst-case bound within $1.50.** Conditional cache-write applicability/accounting, actual provider tokenization, acceptance of full-input-plus-output context and failed-request billing remain unverified. The stress calculation is not a proven ceiling. The plan correctly distinguishes request-count protection from monetary control. Before any paid authorization, settle relevant rates/account controls and scope/token assumptions, or obtain a revised explicit decision; do not silently use the conditional scenario as permission to spend more. This is a live-authorization blocker, not a reason to withhold the offline patch from a PR.

## 7. Publication hygiene and decision

All 14 existing patch/report files were inspected; none exceeds 1 MiB or matches the checked common token/private-key patterns. Manual source inspection found only blank placeholders or explicitly synthetic credentials. `.gitignore` checks cover `.env`, `.env.local`, `.venv`, `.cache`, Chroma files, SQLite/WAL and `tmp/approval.json`. No generated database/cache/environment is among the publication candidates. Pattern checks are not a universal secret detector; final staging should use an explicit reviewed file list. Local artifact paths and this machine's username in reports are reproducibility references, not secrets, but reports are not portable without the documented environment/resources.

**Safe to submit this exact patch as a PR: yes, with these documented limitations.** No new blocking code issue was found. **Ready for limited live-acceptance preparation: yes. Ready to execute paid calls now: no.** First resolve the money-bound uncertainty and obtain fresh explicit consent bound to final sources, fixed registry, exact scope/provider/model and request ceiling. Real-route compatibility remains an acceptance test, with first failures retained and no automatic retry. Publication/merge, provisioning or spending still require the user's applicable explicit authorization.

Only this report was added during review. No production changes, credentials, real provider requests, paid runs, commits, pushes, merges, tags or frozen-data edits occurred.

**APPROVED WITH DOCUMENTED LIMITATIONS**
