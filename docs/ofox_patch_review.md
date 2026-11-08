# Independent review: OfoxAI demonstration and budget guard

Review date: **8 November 2026 (Asia/Hong_Kong)**.

Verified base: **`4bd307bf9c1eee68eb92cb43e821d968206b2c4c`**.

Reviewed application/frozen-input fingerprint: `35d18bd98171c3848bd6f35aac90102bbe2713ff855ec2298fa020ef67df8dd9`.

**Recommendation: changes required before live acceptance.** The existing 185 tests reproduce successfully, but independent provisioning fault probes expose two fail-closed/source-consent defects. The pinned upstream/endpoint combination also needs documentary clarification. Do not configure the live execution environment, provision a real approval registry or submit paid requests on the basis of the current readiness statement.

## 1. Scope and changed-file review

The worktree is detached at the expected base. All pre-existing modified/untracked files were fingerprinted before review and verified unchanged afterward. The only repository addition made by this review is this report. New fault probes/logs are outside Git; no production fix was implemented.

| File | Review assessment |
| --- | --- |
| `.env.example` | Adds blank OFOX_API_KEY and explicit optional profile guidance; no credential value. |
| `.gitignore` | Adds `.venv` to cover the reused environment symlink; no unrelated change. |
| `README.md` | Documents the opt-in profile and separates new demonstrations from historical scores. |
| `app.py` | Checks the acceptance profile before invoking cached services; uses a separate key variable; clears stale results before submit/error paths. |
| `src/rag_app/demo.py` | Adds OfoxAI routing and the profile lock while retaining original baseline/DeepSeek implementations. |
| `src/rag_app/demo_budget.py` | Implements fixed registry, exclusive provisioning, SQLite case claims/reservations, source/path binding and first-result storage. Findings R1/R2 concern provisioning. |
| `src/rag_app/ofox_demo.py` | Adds the isolated provider adapter/transport, frozen evidence checks, shared ledger and partial-usage reconciliation. Finding R3 concerns the exact routing choice. |
| `tests/test_ofox_demo.py` | Thirty useful adapter/guard tests; all pass independently. Missing provisioning race and final-directory-fsync failure coverage exposed R1/R2. |
| `docs/ofox_demo_approval.example.json` | Remains approved=false with null root/source binding. It is not executable consent. |
| `docs/live_demo_acceptance_plan.md` | Contains exact cases, sequence, limits, credential hygiene, stop conditions and semantic checklist. Its readiness assessment must account for R1–R3; R4 corrects the coarse estimate. |
| `docs/final_integration_acceptance.md` | Pre-existing uncommitted report copy, byte-identical and preserved; not a new implementation change. |

No changes were found in Member A ingestion/embedding/storage, Member B retrieval, the original config/ChatClient/QAService/validator, dependencies, source catalogs or frozen experiment directories. All twenty candidate code/input locks and every current runtime-manifest entry validate. The original acceptance report SHA-256 remains `1da6d6b70657ec690c36f83ba3337ca2163b596364edbc6cdb1e59d55b05590f`.

## 2. Findings, ranked by severity

No P0 emergency or unconditional remote vulnerability was established. The following P2 findings block this controlled paid acceptance because explicit consent and fail-closed provisioning are required. R1 is a concurrent source-change race, not a claim that an arbitrary remote actor can edit local files.

### R1 — P2: persisted source fingerprint can differ from the approved fingerprint

**Location:** `src/rag_app/demo_budget.py:84` and **`:102`**.

Provisioning validates approval.source_sha256 against one `fingerprint()` call, then inserts a newly computed fingerprint into meta. If sources/frozen inputs change between those reads, the registry can bind the changed bytes even though consent approved the previous fingerprint. Subsequent checks accept that new fingerprint; consent_hash still identifies approval of the old one.

Independent deterministic probe: the first fingerprint read returns the approved value, the insertion read returns a different value, and later reads return the latter. Provisioning and check both succeed; a GuardedTransport request reaches **one synthetic upstream dispatch**. The safety assertion requiring zero dispatches fails. No production/frozen file was edited: only the two reads were fault-injected to simulate the change window.

**Minimal fix:** persist the exact approved fingerprint, never substitute a fresh value at insertion. Recheck unchanged bytes before activation; on drift, fail closed with an unusable/quarantined registry. Add a regression covering a change between validation and insertion, asserting no dispatch and no implicit approval of the new bytes.

### R2 — P2: failed provisioning can leave an active, usable session

**Location:** `src/rag_app/demo_budget.py:93-112`, especially **`:102`** and **`:108`**.

The registry commits state=active before the parent-directory fsync. An os.open/fsync failure then raises BudgetBlocked, but does not invalidate that committed active state. A new service can accept the registry despite provisioning reporting failure. This contradicts the requirement to stop on audit/durability failure and not resume automatically.

Independent probe: inject OSError at the final directory fsync; provision raises BudgetBlocked as expected. Reopen the resulting file: check succeeds and **one synthetic upstream dispatch** is allowed. The safety assertion requiring zero dispatches fails.

**Minimal fix:** create a non-dispatchable initializing state, complete required filesystem durability checks, then activate it transactionally. Any failure must leave the registry non-active, including after reopening/restarting. Do not delete/reset/recreate it automatically. Add a post-commit fsync failure regression that proves a new service cannot dispatch.

### R3 — P2: resolve the pinned upstream/endpoint documentation conflict

**Location:** `src/rag_app/ofox_demo.py:89-95`, particularly `extra_body.provider.type=openai` paired with `/chat/completions`.

The current [model-specific OfoxAI page](https://ofox.ai/models/openai/gpt-6-luna) lists Chat Completions and Responses for Azure, but only Responses for the pinned OpenAI channel. Generic GPT docs are broader. Thus the exact pinned combination is not established by the most specific documentation. **No live rejection was tested or asserted.**

**Minimal resolution:** obtain authoritative confirmation of this exact pairing, or separately review an explicitly supported route through the same approved OfoxAI domain. A supported Azure Chat Completions route or an OpenAI Responses adapter are possible alternatives, not changes approved by this report. Do not silently switch channels/domains, enable fallback or spend requests probing alternatives. Update route/schema tests, consent fingerprint and plan after the decision.

### R4 — P3: the coarse full-context cost estimate uses the wrong tier

**Location:** `docs/live_demo_acceptance_plan.md:89-91`.

The [current model page](https://ofox.ai/models/openai/gpt-6-luna) lists $0.10/$0.50 per million input/output tokens up to 272,000 input tokens, and $0.20/$0.75 above that threshold. The six-times-100,000 working estimate of $0.0636 is consistent. The stated full-context calculation should instead be about **$1.2636912**, not $0.633, for its own 1,048,576-input-token assumption and 7,200 total output tokens.

**Minimal correction:** document both tiers, fix the coarse equation/allowance, or explicitly limit the estimate to the measured small fixed payloads. Neither calculation is a guaranteed account/billing cap. The plan's $1 allowance cannot be justified by its incorrect full-context calculation; obtain fresh monetary consent after correction. No price/model API call was made.

## 3. OfoxAI protocol compatibility

Documentation checked against the actual wire envelope, using public pages only:

| Aspect | Assessment |
| --- | --- |
| Host/path/auth | Generic Chat Completions endpoint and Bearer auth match [OfoxAI's API documentation](https://ofox.ai/docs/api/openai/chat-completions). No alternate host selected. |
| Model | Exact Luna identifier is documented; exact channel/endpoint support is subject to R3. |
| JSON output | Generic response_format support and GPT structured output are documented. Actual Luna JSON-mode behavior remains unverified. |
| Reasoning | Low is a common effort value, not proven for every model. [Reasoning documentation](https://ofox.ai/docs/develop/models/gpt/reasoning) says unsupported values can fail and reasoning counts against completion tokens. |
| Temperature/thinking | Both omitted. This avoids assuming Luna accepts temperature=0 and avoids sending DeepSeek-specific thinking. |
| Output bound | max_completion_tokens=1200 follows [GPT Chat Completions guidance](https://ofox.ai/docs/develop/models/gpt); max_tokens is also documented as accepted. The small reasoning/output budget can cause truncation; no retry or automatic increase is implemented. |
| Response shape | String content, exact requested returned model and finish_reason=stop are required. Missing/null/non-string, malformed, empty or oversized output fails closed. Live alias/version reporting may differ and needs acceptance verification. |
| Routing/fallback | Literal extra_body matches [routing docs](https://ofox.ai/docs/api/provider-routing); empty backup list supplies no requested fallback models. [Fallback docs](https://ofox.ai/docs/develop/advanced/fallback) describe explicit backup models. Provider-internal behavior is not independently observable here. |
| Errors/timeouts | Zero client retries, no redirects/environment proxies, 120-second request/total deadline. Non-200, model/shape failures, timeout or ledger failures stop the wrapper's session. Sanitized errors do not expose keys/headers/provider bodies. |
| Usage | Whitelisted nonnegative integer token counters are recorded at the transport boundary. Partial selection usage survives later failure; missing usage is partial/unknown, not zero. Reasoning detail counters and actual monetary charges are not independently verified. |

The individual model page loaded successfully during this review, although one subsequent request failed transiently. That documentation-fetch failure is not an API inference failure or evidence of a failed live model call. Nothing in these checks demonstrates real account availability, parameter support, price guarantees or semantic answer quality.

## 4. Security/concurrency boundaries

### Verified controls

- BEGIN IMMEDIATE plus synchronous commits serialize case claims and stage reservations across threads/processes. Only one concurrent claim succeeds. All clients/stages use one count at the configured fixed path.
- Reservations commit before upstream factory construction. A seventh attempt is rejected before construction/dispatch. This also held when invoking **OfoxChatClient directly** with an exhausted ledger, not only through the outer QA wrapper.
- A real child-process SIGKILL immediately after reservation left one reserved attempt and an interrupted case. A fresh interpreter could not replay it.
- An exclusive SQLite database lock blocked begin without adding a reservation. Corrupt/missing stores and injected audit failures are covered by the passing focused tests.
- A mocked upstream that received a request and then raised ReadTimeout left one consumed error attempt, stopped the session and blocked generation. Second-stage failure tests retain known selection usage and first-result evidence.
- Repeated/out-of-order/non-exact questions, renamed session/output labels, different paths, copied ledgers and symlink aliases are blocked by the tested entry points. Fixed OS-account home is used on POSIX instead of HOME/session environment overrides.
- Streamlit checks the profile before invoking a cached baseline service. With a registry present, choosing baseline/DeepSeek is blocked. Existing profiles remain compatible when no registry exists.

### Explicit limits

This is an application-local guard, not a sandbox around an API key. Someone who controls the Python process, filesystem or key can call an unrelated generic client/raw HTTP, change code or tamper with SQLite. An ordinary direct Ofox client still uses GuardedTransport, but arbitrary caller-supplied replacement code/factories are not an adversarial security boundary.

A separate synthetic probe restored an earlier database backup **at the same approved path** and observed the old counter/state. That is an established rollback limitation under the plan's explicitly excluded filesystem-tampering boundary, not a remote exploit or proof the normal six-attempt transaction fails. The guard cannot enforce account-wide spend or resist an operator restoring/deleting its own files. Protect the registry, prohibit restores/reset, and stop all earlier provider-capable processes/sessions before provisioning. An already in-flight generic-profile request is not retroactively brought under the ledger by the profile gate.

R1/R2 are distinct from these exclusions: they are provisioning ordering/error-handling defects reproducible with normal source drift or an injected filesystem failure, without editing a registry or bypassing the intended transport.

## 5. RAG, provenance and historical compatibility

Tracing the profile confirms original JointCandidateRetriever -> eight source chunks -> prepare_evidence/catalog join -> original evidence planner -> separate final model request -> original citation validator -> Streamlit text/source display. The first five chunk IDs, original source text/URLs/document IDs and physical PDF pages match the frozen contexts. Unknown/superseded status remains catalog-derived; quotation membership does not prove semantic entailment.

Independent real-index execution used a copy of the existing Chroma store and cached MiniLM, with synthetic consent/key/HTTP only. It returned EXP11 answered with FSB page 6, EXP30 answered with HKMA page 5 and FSB page 59, and EXP-R07 whole-question refusal. The sequence was exactly two/two/one mocked dispatches. These are pipeline observations, not Luna answer-quality scores.

Historical sources, JSONL/corpora, frozen inputs/prompts, result hashes, original DeepSeek profiles, validator and full40 authorization runtime remain unchanged. Runtime hashes and all twenty candidate lock entries match. No historical score or provenance record was rewritten. The new-profile and experiment-origin labels keep these QA records separate from historical results. Source filenames remain in Chroma rather than the existing B RetrievalHit contract; essential citation metadata is preserved.

## 6. Independently reproduced verification

All runs used the existing combined Python 3.11 environment, offline Hugging Face flags, credential stripping, disabled dotenv and an external-network audit hook. Synthetic keys/MockTransport only. No install/download or real credential/registry operation was performed.

Artifacts, scripts, exact child commands, exits and first-run logs:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/ofox-independent-review-20261108`

| Run | First-run actual result |
| --- | --- |
| Complete repository/experiment suite | **185 passed**, 57 dependency warnings, zero skips; 11.81 seconds pytest time |
| Focused adapter/guard suite | **30 passed**, 5 warnings; 2.10 seconds |
| Independent initial five boundary probes | **2 failed, 3 passed**; 2.38 seconds. The two failures reproduce R1/R2 and remain unresolved. |
| Two subsequently added direct-client/timeout probes | **2 passed, 5 deselected**; 0.14 seconds. Only the new probes were selected; the original failures were not rerun or hidden. |
| Real-index three-case pipeline | Five mock dispatches; expected answers/refusal and original citations; zero real calls |
| Historical preflight | **30 checks passed**, zero real upstream requests/credential reads |
| Frozen replay | **40 contexts / 320 evidence blocks matched**, max distance delta `2.72e-07` |

Commands from the worktree, through the saved run_offline.py (set ART to the artifact directory above):

```bash
python3 "$ART/run_offline.py" independent_full_first -m pytest -q -p no:cacheprovider tests experiments
python3 "$ART/run_offline.py" independent_focused_first -m pytest -q -p no:cacheprovider tests/test_ofox_demo.py
python3 "$ART/run_offline.py" independent_boundaries_first -m pytest -q -p no:cacheprovider "$ART/test_independent_boundaries.py"
python3 "$ART/run_offline.py" independent_additional_first -m pytest -q -p no:cacheprovider "$ART/test_independent_boundaries.py" -k 'direct_ofox or timeout_after'
python3 "$ART/run_offline.py" independent_real_index_first "$ART/independent_real_index.py"
python3 "$ART/run_offline.py" independent_preflight_first experiments/generative40/preflight_controller80.py \
  --runtime experiments/generative40/runtime --app-src src --output "$ART/preflight"
python3 "$ART/run_offline.py" independent_replay_first experiments/joint_pairs8/verify_replay.py \
  --experiment-dir "$ART/index_copy" --cache-dir .cache/huggingface/hub
```

Use new labels/output directories for new runs: logs are exclusively created. The initial boundary file contained five probes when its command ran; two more were added afterward. To reproduce just those original five against the current seven-probe file, add `-k 'not direct_ofox and not timeout_after'`. No production fix, test-result correction or silent retry was performed in this review. The earlier author's fault-injection/sandbox failures remain separately recorded in the existing plan; they are not failures observed in this review's 185-test run.

The two failing tests are intentionally retained outside the repository as concrete regression specifications. All these results are local; no GitHub CI or unseen-test performance is claimed.

## 7. Required steps before live acceptance

1. Obtain approval for minimal R1/R2 fixes, add both provisioning regressions to the repository and rerun focused/full offline suites. Both new safety probes must become passing without weakening their zero-dispatch assertions.
2. Resolve R3 with model/channel-specific documentation or a separately reviewed supported adapter/route. Do not change the provider domain, silently fall back or make an exploratory paid request.
3. Correct R4 and obtain a newly agreed cost allowance. Preserve the distinction between a client request ceiling and billing/account limits.
4. Recompute the fingerprint only after the final reviewed patch is fixed. Keep the shipped template unapproved. Never reuse historical full40 consent or a synthetic test approval.
5. Only then consider local credential setup and a separate explicit approval for the exact three first-response cases, fixed canonical registry, expected five attempts and maximum six. Recheck source/index/catalog and stop other provider-capable sessions. Preserve first failures and perform human semantic citation review.

No production code, frozen evidence, prior report, approval or real key was changed. No paid request, commit, push, merge, tag, worktree reset or deletion occurred. This report is not authorization to spend or to implement the proposed fixes.

CHANGES REQUIRED BEFORE LIVE ACCEPTANCE
