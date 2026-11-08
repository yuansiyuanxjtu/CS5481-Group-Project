# OfoxAI provisioning security fixes — offline verification

8 November 2026, Asia/Hong_Kong. Base: `4bd307bf9c1eee68eb92cb43e821d968206b2c4c`, detached isolated worktree. This is targeted remediation, not a new independent review or paid acceptance. No credentials were read, paid requests made, live approvals/registries created, or Git commits/pushes/merges/tags performed.

## Root causes and changes

1. **Approval-binding race:** provisioning compared approval with one `fingerprint()` result, then persisted a fresh result. A source mutation between those operations could become the accepted version. The patch saves the exact approved fingerprint, checks it before persistence, before activation and after the activation commit, and retains runtime fingerprint checks before ledger operations. A detected mismatch permanently blocks that incomplete provisioning, even if files later return to their approved version.
2. **Failed provisioning usable after reopen:** an active row was committed before a fallible directory fsync. The operation could raise while leaving usable consent. The patch exclusively creates and flushes a sibling `.provisioning` fence before initializing SQLite. Every transaction refuses that fence. All durable writes/syncs complete under it; final unlink is the last fallible operation and successful activation point. No I/O follows release. Failures leave the fence authoritative even if SQL says active. Marker-only initialization also blocks profile switching and reprovisioning. Losing the final unlink on power failure may cause safe unavailability, never a fresh budget. There is no automatic fence cleanup or reset.

Only these four repository files changed during this remediation:

| File | Change |
| --- | --- |
| `src/rag_app/demo_budget.py` | Approved-value persistence, repeat source checks, durable provisioning fence, profile/transaction fence checks and commit fault-injection seam |
| `tests/test_ofox_provisioning.py` | 19 synthetic regression cases |
| `docs/live_demo_acceptance_plan.md` | Provisioning protocol, official compatibility recheck, corrected tiered cost assumptions and planning-only allowance |
| `docs/ofox_security_fix_verification.md` | This report |

The existing uncommitted Ofox profile work remains present: `.env.example`, `.gitignore`, `README.md`, `app.py`, `src/rag_app/demo.py`, `src/rag_app/ofox_demo.py`, `tests/test_ofox_demo.py`, approval example and prior reports. Their bytes were preserved. `docs/ofox_patch_review.md` and `docs/final_integration_acceptance.md` were not rewritten.

## Attack reproduction and regression coverage

Before editing production code, the independent review's original two attack probes were copied and run against the original runtime. **Both failed their safety assertion**, each allowing **one unexpected synthetic HTTP dispatch**. Saved original source, probes, command/exit JSON and failure logs remain outside Git.

After patching, all **seven independent probes passed**. The approval-race probe's after-copy accepts the newly early `BudgetBlocked` from provisioning; the original probe assumed provisioning would return and only checked rejection later. This oracle adjustment is explicit and preserved as a separate file. It does not permit a request: both former attacks terminate at a rejection before `dispatch_one`, so unexpected provider dispatches are **zero**. Original probes/logs are untouched. The five other independent probes cover exclusive locks, killed reserved attempts, same-path filesystem rollback boundary, seventh-request blocking and timeout-after-receipt consumption.

The 19 new repository cases cover:

- Source drift before persistence, before activation and after activation commit; persisted value remains the approved value.
- Commit faults before/after both commits; every explicit fsync boundary; both stream flush boundaries; final fence-unlink failure.
- Reopen and fresh-process rejection after faults, even when source files return to their approved state.
- Marker-only initialization, profile switching and renamed-session retries.
- SIGKILL after initialization/activation commits; four concurrent provisioners with exactly one winner.
- Successful initialization persisting the approved value and reopening normally.

The prior 30 Ofox tests still cover duplicates, exact questions/order, six/seven boundary, multiple service instances/processes, restart protection, path/copy/symlink/source binding, provider failures, partial usage and audit failures. Original A/B/C, baseline/DeepSeek and historical experiment tests pass unchanged.

## Exact commands and actual outcomes

Run from the worktree above. Artifact directory (`ART`):

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-security-fix-20261108`

`run_offline.py` strips credential-like environment variables, disables dotenv, sets cached/offline model loading, fixes the hash seed and installs the existing audit hook blocking external sockets/DNS. All HTTP provider responses and approval records were synthetic. Logs use exclusive creation; choose new labels for reruns. The `reproduce_before` command describes the retained original-code run, not the expected outcome on patched code.

```bash
ART=/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-security-fix-20261108
python3 "$ART/run_offline.py" reproduce_before -m pytest -q -p no:cacheprovider \
  "$ART/test_independent_boundaries.py" -k 'consent_check or failed_provisioning'
python3 "$ART/run_offline.py" provisioning_first -m pytest -q -p no:cacheprovider \
  tests/test_ofox_provisioning.py tests/test_ofox_demo.py
python3 "$ART/run_offline.py" boundaries_after -m pytest -q -p no:cacheprovider \
  "$ART/test_boundaries_after.py"
python3 "$ART/run_offline.py" full_first -m pytest -q -p no:cacheprovider tests experiments
python3 "$ART/run_offline.py" preflight_first experiments/generative40/preflight_controller80.py \
  --runtime experiments/generative40/runtime --app-src src --output "$ART/preflight"
python3 "$ART/run_offline.py" replay_first experiments/joint_pairs8/verify_replay.py \
  --experiment-dir "$ART/index_copy" --cache-dir .cache/huggingface/hub
python3 "$ART/run_offline.py" real_index_first "$ART/independent_real_index.py"
```

| Run | Actual result |
| --- | --- |
| Original two attacks, before fix | **2 failed, 5 deselected**, exit 1; one unexpected mock dispatch per attack |
| Focused provisioning and Ofox tests | **49 passed**, exit 0, 4.37s pytest |
| Independent probes, after fix | **7 passed**, exit 0, 2.46s |
| Full repository | **204 passed**, exit 0, 14.20s pytest; 57 dependency deprecation warnings, no skips |
| Historical offline preflight | **30 checks passed**; zero real upstream requests/key reads; all answers/usage synthetic |
| Frozen retrieval replay, copied database | **40 contexts / 320 blocks matched**, maximum distance difference `2.72e-07` |
| Real-index mock adapter | **5 synthetic dispatches**: EXP11 answered, EXP30 answered, EXP-R07 refused; zero real requests |

No post-fix test run failed or was silently retried. A subsequent artifact-binding helper initially used the system Python (older than the project requirement), failing on the existing Python 3.11 union annotation before computing the application fingerprint. The hash-file export succeeded; fingerprint export was then rerun through the offline runner with the project interpreter. This was a metadata-helper failure, not a test or application regression. The only post-run test edit removed an unused import; no assertions or production source changed after the full-suite run. Earlier historical author's test-target and sandbox failures remain recorded in the acceptance plan. This evidence is **local**, not GitHub CI.

Real-index citations: EXP11 FSB 2024 physical page 6; EXP30 HKMA 2026 physical page 5 and FSB 2026 physical page 59. All three cases matched their frozen retrieved chunk IDs. Synthetic usage 20/20/10 is not Luna billing or semantic-quality measurement.

## Frozen compatibility and evidence binding

`before_sha256.json` captured every preexisting modified/untracked file. Preservation checks show only the budget module and acceptance plan changed among those files. All **87 tracked files under experiments/data/config/src (excluding the already-modified demo dispatcher)** match base HEAD byte-for-byte. This includes historical runtime/manifests, prompts, retrieval algorithms, frozen inputs, scores and results. Existing original reports and approval example remain unchanged. No historical fingerprints were regenerated. Replay used a copied database, not a rebuild of the original.

Artifacts include `protected_sha256.json`, `preservation_check.json` and final source/test/document hashes in `final_sha256.json`; `final_binding.json` records the current application fingerprint. That current fingerprint intentionally differs from the old patch: any hypothetical older approval would fail binding. No real approval was edited or generated.

## Provider and cost findings

Retain the fixed Chat Completions endpoint/model, low reasoning, JSON mode, 1,200 completion limit, omitted temperature and explicit OpenAI routing with no fallback. [GPT family](https://ofox.ai/docs/develop/models/gpt), the [model page](https://ofox.ai/models/openai/gpt-6-luna) introduction/example and [Chat reference](https://ofox.ai/docs/api/openai/chat-completions) support this interface. The model's OpenAI-specific protocol table lists only Responses, while Azure lists both: document this unresolved listing contradiction without claiming observed incompatibility or migrating endpoints.

[Routing documentation](https://ofox.ai/docs/api/provider-routing) supports body provider selection; an additional routing header is unnecessary. [Reasoning documentation](https://ofox.ai/docs/develop/models/gpt/reasoning) places reasoning within completion usage. Low effort and JSON compatibility for this exact route remain unverified; only `stop`, exact model identity and string content are accepted. Length/refusal/malformed/error outcomes stop, without alternative paid probes. Ledger totals preserve reported prompt/completion/total usage, including completion reasoning when the provider includes it; missing or partial usage is not zero and no separate measured reasoning total is claimed.

The updated acceptance plan itemizes uncached, cache-read and conditional cache-write scenarios for both context tiers. Six full-context uncached calls estimate **$1.2636912**, correcting ~$0.633. User selected **$1.50 proposed allowance only**, not paid authorization. Conditional high-context cache-write stress estimates **$1.578264** and exceeds that proposal; applicability/accounting is unresolved and must be settled before live approval. No cache savings, monetary cap or new authorization is inferred. Six requests is a dispatch limit, not a dollar ceiling.

## Remaining boundaries and readiness

Trusted account/operator and intact local filesystem are required. Same-path rollback, deleting fences/registries, edited Python, another program using the key, provider-internal behavior and physical-storage guarantees are outside this local guard. Failed provisioning deliberately sacrifices availability and has no automatic recovery. Tests exercise process interruption and injected persistence errors, not physical power-loss hardware. Windows behavior was not verified.

Live route-specific parameter support, token accounting, cache charges, prices/account controls and fresh explicit paid consent remain prerequisites. No live session was started. The patch is suitable for final independent review; this report does not approve spending or merge/publish anything.

**READY FOR FINAL INDEPENDENT REVIEW**
