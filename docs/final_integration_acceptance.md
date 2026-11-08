# Final A+B+C integration acceptance

Review date: **8 November 2026 (Asia/Hong_Kong)**.

**Verdict: READY WITH DOCUMENTED LIMITATIONS.** The merged application passes offline engineering acceptance and is ready for a separately authorized, limited live-provider demonstration. No live demonstration or new answer-accuracy evaluation was performed in this review.

## 1. Exact repository state and review boundaries

- Repository: <https://github.com/yuansiyuanxjtu/CS5481-Group-Project>.
- Verified remote main and clean review checkout HEAD: **`4bd307bf9c1eee68eb92cb43e821d968206b2c4c`**.
- [PR #3](https://github.com/yuansiyuanxjtu/CS5481-Group-Project/pull/3) is merged, merge commit `21797ca3a5d4d1675f30a31b622c29c62c137086`; its head includes security fix `9ec199f8d2f9abb2e069dfa3d23ef6263bc0b09e`.
- [PR #4](https://github.com/yuansiyuanxjtu/CS5481-Group-Project/pull/4) is merged, merge commit `4bd307bf9c1eee68eb92cb43e821d968206b2c4c`; reviewed demo head `f6eabeac6829badbc451f8cffc41ec8ee3f8d5c0`.
- The supplied isolated worktree was clean at detached `9ec199f` before work. It was not reset, switched or discarded. Remote main was fetched into a new temporary repository, then checked out detached at the expected merge commit.
- All **163 tracked files** of fetched main matched the previously verified current-main-plus-PR-#4 integration, byte for byte. This confirms the actual merge preserved the security/provenance patch; the old synthetic merge ref from the pre-merge review was not used.
- The only deliverable repository change is this uncommitted report. Application/retrieval code, historical results, prompts, frozen inputs, source catalogs and dependency locks were not edited. No commit, push, PR, tag or merge was created.

Instructions/context reviewed: `AGENTS.md`, `README.md`, A's dataset/quality/temporal documentation and `docs/member_b_handoff.md`, B's `docs/retrieval_evaluation.md`, C's `docs/member_c_handoff.md`, and the generative40/joint_pairs8 documentation.

## 2. Architecture and interface acceptance

```text
Five pinned official-source English PDFs + sources.csv
  -> rag_ingest.manifest / pdf: validate provenance, extract and clean physical pages
  -> rag_ingest.chunking: pinned fast-tokenizer windows, deterministic IDs, no page merging
  -> UTF-8 JSONL: separate chunk strategies
  -> MiniLMEncoder: cached pinned model, normalized 384-dimensional vectors
  -> persistent Chroma: checked model/strategy/context, cosine distance
  -> JointCandidateRetriever: reviewed joint_pairs8, eight original chunks
  -> QAService.prepare_evidence: temporal catalog join and source checks
  -> frozen evidence-selection prompt + model plan
  -> frozen final-answer prompt + separate LLM generation request
  -> original validate_generation: schema and exact-quotation checks
  -> Streamlit answer, citations, physical-page links, status warnings and QA download
```

### A: data, embeddings and storage

The original CSV contract remains `document_id,source_file,source_url`. Chunk JSONL retains `chunk_id`, `document_id`, `source_file`, `source_url`, one-based `page_number`, `text`, `chunk_strategy`, and `token_count`. IDs include document/page/index/strategy; chunks never combine physical pages. Cleaning and tokenization are deterministic for the pinned inputs/configuration. Phase 2.6 enhanced cleaning is isolated from the original pilot.

MiniLM is `sentence-transformers/all-MiniLM-L6-v2`, immutable revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`, CPU/offline loading, 384-dimensional normalized embeddings and a 256-token input limit including special tokens. Chroma configuration/context checks remain active; this review neither recreated nor wrote records to an existing database.

### B: reviewed retrieval and metadata

`RAG_DEMO_PROFILE=joint_pairs8` constructs the actual `JointCandidateRetriever`. Its code lock is checked before use; each result must contain exactly eight distinct chunks and preserve the documented five-chunk prefix. The remaining three come from the reviewed joint selection. There is no silent profile fallback to baseline. Unknown profiles fail during setup.

Retrieval returns original chunk/document IDs, text, source URLs, physical PDF pages, title/date/status and cosine distances. C checks the URL against the catalog and derives source cards/page links from those records. **Source filename, token count and strategy remain stored in Chroma but are not exported by B's existing RetrievalHit contract.** This does not break the present citation interface; downstream archival joins should use document/chunk IDs and the catalog, not assume those extra fields are in a QA record.

### C: planning, final generation, validation and UI

The cached service reuses the retriever/encoder but creates a fresh `PlannedGenerationClient` per submission, resetting per-question plan/duplicate/call state. A declared unsupported required part causes whole-question refusal after selection, with no second request. A supported plan invokes the LLM for a separate final response; deterministic quote rendering does not replace that final content. The original `QAService.validate_generation` remains active.

Both frozen prompts are checked. The selected profile uses direct DeepSeek `deepseek-flash`, temperature 0, JSON mode, thinking disabled, at most 1,200 output tokens and a 120-second deadline **per request**, enhanced `fixed_150_overlap_30`, top_k=8 and no uncalibrated distance cutoff. The new versioned runtime manifest from PR #3 is compatible; the demo checks unchanged method/prompt files and does not invoke the trial launcher.

Invalid input, retrieval failure, unsupported evidence, provider failure and invalid model output remain separate states. Invalid IDs or quotes not present in the numbered chunk fail closed. Claims/quotes render as text; links and provenance are not generated by the model. Submissions clear previous answers before blank-input/configuration/provider errors. Physical-page labels remain authoritative when a PDF viewer ignores URL fragments.

## 3. Environment and reproducible test commands

Actual environment: macOS arm64, CPython **3.11.15**, existing combined application virtualenv and cached model. `python -m pip check` reported **No broken requirements found**. No dependencies/models were installed or downloaded. Pip warned that its cache directory was not writable and disabled that cache; this did not affect dependency checking.

Use `requirements-app-lock.txt` for a fresh combined app environment. Do not install the historical phase2 lock over it: the app lock uses the documented Pillow 12 compatibility override for Streamlit. README acquisition/model preparation commands require separate deliberate network access on a new machine; they were not needed here.

Review checkout: `/private/tmp/cs5481-final-acceptance-20261108`.

Machine-local verification artifacts, scripts, first-run logs, corrections and screenshots:

`/Users/yuansiyuan66/.codex/visualizations/2026/11/02/01a19c93-4b04-75b1-819a-4e20d70d1b89/final-acceptance-20261108`

These artifacts are outside Git. The checkout has only an ignored cache symlink for existing offline test assets. The runner strips credential-like environment variables, disables dotenv, sets offline Hugging Face flags and injects an audit hook that blocks external socket connections/DNS. Tests supply only synthetic keys and MockTransport responses. The browser server binds localhost only.

Commands below reproduce the command shapes. Set `PY` to the existing combined environment's Python and `ART` to the artifact directory above, and run from the review checkout. Use **new labels** and fresh output directories on subsequent runs; the runner opens logs exclusively to preserve prior evidence.

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0

# The runner executes the required complete test command with the safeguards above:
"$PY" "$ART/run_acceptance.py" full_first -m pytest -q -p no:cacheprovider tests experiments
"$PY" "$ART/run_acceptance.py" pip_check_first -m pip check
"$PY" "$ART/run_acceptance.py" data_first "$ART/audit_data.py"
"$PY" "$ART/run_acceptance.py" preflight_first experiments/generative40/preflight_controller80.py \
  --runtime experiments/generative40/runtime --app-src src \
  --output /private/tmp/cs5481-final-preflight-20261108
"$PY" "$ART/run_acceptance.py" replay_first experiments/joint_pairs8/verify_replay.py \
  --experiment-dir "$ART/index_copy" --cache-dir .cache/huggingface/hub
"$PY" "$ART/run_acceptance.py" offline_app_final -m pytest -q -p no:cacheprovider \
  "$ART/test_offline_acceptance.py"
```

The exact interpreter, command, working directory, exit code and elapsed time are retained in each `*.json` log companion. The four additional acceptance tests/harness are external review code, not new repository features/tests.

| Check | Actual outcome |
| --- | --- |
| Complete repository + experiment suite, first execution | **155 passed, 57 warnings, zero skips**, 10.83 seconds pytest time |
| Authorization regressions included in that suite | **14 tests passed**, covering root binding, relative/symlink aliases, cross-root blocking before side effects, same-root/renamed-output replay and separately approved roots |
| Offline orchestration preflight, first execution | **30 checks passed**; 80 main-trial mock dispatches; 360 stage events; zero real calls/credential reads |
| Five-document/data/model audit, first execution | All five SHA-256 values/pages, two identical ingestion runs and selected-index checks passed |
| Frozen offline replay, first execution | **40 contexts / 320 evidence blocks verified**, max distance difference **2.72e-07** |
| Additional actual-index service/Streamlit tests, final external-harness version | **4 passed, 9 warnings**, 5.29 seconds pytest time; initial harness failures are retained below |
| Dependency consistency | No broken requirements |

The 57 repository warnings are existing PyMuPDF/SWIG and Chroma legacy embedding-configuration deprecations. The additional tests report the same families, plus Streamlit bare-mode context notices. No intermittent HNSW read failure was observed. **GitHub CI has not run for this main commit:** zero Actions runs, check runs and status entries were returned. These are local verification results, not CI results.

### First failures and corrections, without silent retries

1. Initial sandboxed Git fetch exited 128 because DNS resolution of github.com was blocked. The explicitly permitted network retry fetched main successfully. No branch/history was rewritten.
2. Repository tests, data audit, preflight and replay passed on their first execution; none was retried to conceal a failure.
3. External `offline_app_first`: **1 passed, 3 failed**. The acceptance-only injection factory recursively called its own monkeypatch for the joint profile; an assertion also incorrectly expected missing usage after a completed but JSON-invalid final response, and its synthetic selection did not cite a historical source for a warning assertion. These are harness/expectation defects, not production changes.
4. External `offline_app_corrected`: **3 passed, 1 failed**. The remaining warning assertion still selected a nonhistorical source unit. The UI correctly warns about *cited* superseded sources, not every retrieved source. The external mock was corrected to select an actual 2019 unit for that test; `offline_app_final` then passed all four tests. Production code, prompts and frozen inputs were untouched. All three logs and exact commands remain in the artifact directory.
5. The first browser server launch failed with sandbox `PermissionError` on localhost bind. The permitted launch succeeded and was stopped cleanly after testing. Sandbox process inspection also initially failed during cleanup; permitted targeted cleanup stopped only the acceptance server. No provider was contacted by either launch.

## 4. Source, ingestion, vector and evidence validation

All five existing local PDFs matched the tracked acquisition catalog **and** the selected run's temporal-catalog document checksums. They contain **165 physical pages**:

| Document ID | Physical pages | SHA-256 |
| --- | ---: | --- |
| `hkma_20191101_ai_principles` | 4 | `588e79c06d1b8d8dc3d400b6ab87491e457472f1b726ad58df67a35e457981ad` |
| `hkma_20261015_ai_guidance` | 8 | `2517b00fba23ed6e4c4372e5f84ad789f23df435cae7ee4d8d500872fc9cb109` |
| `fsb_20241114_ai_stability` | 40 | `4b81544ecb28b50fb2fa5dab530a0f32c9351506a875d1de841b946d18e7ecef` |
| `fsb_20261015_responsible_ai` | 75 | `4e3ea6d2f52439f8aef6a27fc316a20eecacecd50b03dfca4e89f9f1de0ca6de` |
| `bis_20241212_ai_regulation` | 38 | `e0c9275e8dcabb65bc3261f1d930c4f93796fcea6133a569a43338e9f783adce` |

Every extracted document retained consecutive physical-page numbers. Two fresh Phase 1 runs in new artifact directories produced byte-identical outputs, also byte-identical to the existing original pilot:

- `fixed_150`: **753 chunks**, JSONL SHA-256 `63ba41484e3bf937c53cad0a2e52079c71b527fd7884fa7dd6c0f3858158b43b`.
- `fixed_220_overlap_30`: **588 chunks**, JSONL SHA-256 `e295923a4ba655dc81b39d5d4392adad68b366da0c18607919ab8be8be056701`.

Chroma access used a newly copied existing enhanced index, not the source/pilot database. The selected `finance_fixed_150_overlap_30` collection contained **874 distinct records**. All vectors were finite, 384-dimensional and unit-normalized; collection identity/model/revision/cosine/context checks passed. All 874 records had matching document IDs, filenames, original URLs, valid physical-page ranges, strategy, actual tokenizer counts within 150 tokens, and catalog status. The cached real encoder self-match distance was approximately zero (`-1.19e-07`, floating-point tolerance). The copy also contains the existing enhanced 150/0, 220/0 and 220/30 collections; baseline-profile service/UI tests exercised enhanced 150/0. No database was deleted, rebuilt or upserted during this acceptance review, except synthetic temporary stores inherently created by the existing automated tests.

Dataset context: `pilot5_8321c43ee6b1`; dataset SHA-256 `8321c43ee6b19681945f7dfc35d4592c5a8cf2dca66357d5edb0f3356031583d`; cleaning `conservative_margins_v1`; chunking `original_token_windows_v1`. The catalog hash matches the index and frozen generation protocol.

Replay verified all 40 question contexts, all 320 evidence blocks, eight distinct chunks per question, preserved baseline five-chunk prefixes, IDs/order/exact text, catalog-enriched metadata and first-stage request hashes. All **20** code/input entries in `candidate_lock.json` remain valid. Determinism means matching inputs/configuration produce the same contexts within the documented floating-point distance tolerance; it is not a promise of identical cloud answers.

## 5. Streamlit and failure-handling acceptance

Both `baseline` and `joint_pairs8` were exercised using the real local index and cached MiniLM, with injected synthetic HTTP responses. The repository's existing Streamlit regression also passed as part of the 155-test suite.

| Scenario | Observed outcome |
| --- | --- |
| Baseline single-document response | One mocked request, validated citation, usage 10 synthetic tokens |
| Joint supported/cross-document response | Two mocked requests, usage 20; original HKMA physical page 5 and FSB physical page 59 citations |
| Missing requested internal identifier, EXP-R07 | Whole-question refusal, one selection request, usage 10, no final generation/citations |
| Same question submitted repeatedly | Fresh selection and generation each time; no stale duplicate/plan rejection |
| Blank/invalid input | No accepted answer; previous result cleared; existing tests cover null/oversized input without LLM calls |
| Historical source | Superseded 2019 HKMA source cards show the historical warning in both-profile AppTest coverage; baseline browser warning observed |
| Fabricated quotation / out-of-range evidence ID | `invalid_output`, no accepted answer/citations |
| HTTP 503 / injected ReadTimeout in either stage | Sanitized `llm_error`, no provider-body/exception sentinel/key leakage or stale answer |
| Completed HTTP response containing malformed answer JSON | `invalid_output`; no answer accepted |
| New submission after success then failure | Old answer/source links cleared; safe error state displayed |

The **usage limitation is confirmed**: if selection succeeds but generation raises a transport/provider error, the exported error result has `usage: {}` and loses known selection usage. Empty usage must not be interpreted as zero billing. Malformed selection output can similarly lose reported selection usage. In contrast, a completed final response that subsequently fails JSON/citation validation retains both stages' reported usage (20 synthetic tokens in this probe). Successful refusals correctly retain first-stage usage. No accounting fix was implemented.

### Actual browser observations

The unchanged repository `app.py` was executed through an external offline-only wrapper that injected the mock transport and clearly labeled synthetic responses. No production file was modified. The real browser verified:

- joint profile EXP30 answer/source cards with physical pages 5 and 59 and original URLs/chunk IDs;
- EXP-R07 whole-question refusal with no source cards;
- second-stage HTTP 503 producing only a safe generation-error message;
- baseline B05 showing the 2019 document, physical page 4 and a superseded warning.

Screenshots: `browser-cross-document.jpg`, `browser-refusal.jpg`, `browser-provider-error.jpg`, `browser-baseline-historical.jpg` in the external artifact directory. The server was stopped after testing. These are **new browser observations with synthetic model responses**, not historical/provider answer screenshots or semantic accuracy evidence.

## 6. Security, status evidence and frozen provenance

P1 remains fixed in both the launcher and direct authorized `run_trial`: explicit canonical-root binding is checked before initialization, credentials, transport creation or trial files. Same approval/different root is blocked; relative/symlink requests normalize; same-root and changed-filename restarts remain blocked; separately authorized roots remain permitted. The 80-attempt cap, duplicate guard and durable audit remain covered by the authorization/preflight tests. No real authorization or credential was read, generated or modified.

Current manifest version: `canonical-root-bound-v2`.

- Current runtime-manifest SHA-256: `56e24eddfdbdb35fec097811177c70dbc146005a46c2c3100cdcb2ab7f984c49`.
- Current controller SHA-256: `d806595889cdbdbcfa78fc444a7f5b81ce6a519673c3ab3fcf70e6bcc88042bc`.
- Current launcher SHA-256: `8255171bf0d470633d455cba6f6a53646102daa28a959daefdc6041ff98fddc3`.
- Archived v1 manifest SHA-256: `c23200a1ce27c442a21cbe676d10dc87bb230e54ef306bfa3ec057111b0601b5`.

Archived v1 source/fingerprints and historical results remain distinct from patched execution. P3's archived-CLI documentation is present; the supported reproduction is `experiments/joint_pairs8/verify_replay.py`, not the old standalone CLI mains with missing historical inputs.

The catalog's 2019 HKMA `superseded` status was checked against the pinned official successor PDF, physical page 1, whose Purpose section identifies the 2019 principles as superseded. This is local verification of recorded source evidence, not fresh legal-applicability monitoring. Newer documents remain `unknown` where the snapshot says unknown; publication dates/similarity are not used to infer current status. The corpus includes supervisory guidance, non-binding reports and policy research, not five interchangeable binding regulations.

Ignored environments, PDFs, generated JSONL/DB/model files and `.env` secrets remain excluded by `.gitignore`. No real keys/provider bodies were printed, persisted or sent. The browser displayed synthetic sentinel-free failures and original-source citation links only.

## 7. Historical results and remaining limitations

The historical joint_pairs8 record reports **29/30 core correctness**, **28/30 complete supported answers**, **10/10 whole-question refusals**, and **69 successful requests**. These are the preserved exposed development-regression results, **not** new offline accuracy measurements or independent unseen-test results. A/B/C automated engineering checks and this review's mocked outputs must not be added to those score denominators.

- **EXP28:** answerable cross-document question still refused because the eight chunks lacked the necessary BIS passage about differing AI definitions across jurisdictions. It remains a retrieval/coverage miss, not a successful refusal example.
- **EXP05:** core facts were accepted historically, but one selected quote did not support the full ongoing-monitoring scope of its claim. It remains a quote-support limitation, not a fully supported success example.
- Quote membership proves source provenance, not entailment, completeness, legal applicability or resistance to all prompt injection. Mechanical question-part/sentence splitting is fallible; semantic decisions still depend on the model and human review.
- Live model responses/service conditions can vary. No real-provider latency, availability, billing, safety or repeatability was newly tested. Windows, non-ASCII native-HNSW paths and other platforms were not newly validated; frozen runtime checks require the expected LF bytes. The prior intermittent HNSW issue was not reproduced, not disproved.
- The application defaults to **baseline**. Set `RAG_DEMO_PROFILE=joint_pairs8` explicitly and restart Streamlit for the reviewed two-stage demo. Cached service settings require restart after configuration/key changes.
- The demo does not use the formal trial launcher's authorization/80-attempt ledger. Browser submissions therefore require an operator-controlled budget and separate live-demo approval; this offline report is not that approval.
- Partial-usage loss is a known operational limitation. The QA download is not a complete billing ledger on failures.
- Some handoff text describes historical branch states/Windows newline workarounds and old test counts. Preserve those historical records; use this exact verified commit, current README/C combined-environment instructions and newly recorded commands for release acceptance.

No blocking production defect was found. Any future accounting/portability improvement should be a separate approved targeted change; none is implemented here.

## 8. Proposed limited live-provider acceptance plan — NOT EXECUTED

Proposed scope: exactly three manual submissions using the joint profile, one first response each, no retries/recovery, no new baseline/evaluation run. The historical observations below guide review; **the same answer is not guaranteed to recur**.

### A. Single-document: EXP11

**Question:** What longer-term changes does the FSB's 2024 executive summary say AI uptake could drive beyond the immediate vulnerabilities it discusses?

Historical expected behavior: answered, with the changes involving market structure, macroeconomic conditions and energy use, retaining the conditional implications for financial markets/institutions. The frozen context includes the relevant FSB physical page 6 passage. Historical B review accepted the core fact and full quote support.

Exercises: local encoder/index, eight-chunk retriever, selection, final generation, exact quotations, single-source display and usage aggregation. Presenter should inspect the actual full claim and its original page-6 quote/link, avoid turning a conditional possibility into a certainty, and confirm two reported stages. Risks: false refusal, incomplete list/conditions, cloud response variability or service failure.

### B. Cross-document: EXP30

**Question:** In the FSB's 2026 multi-agent case example, what does the log record besides final outcomes, and which optional GenAI records does the HKMA's 2026 guidance give as examples for tracing material outputs?

Historical expected behavior: answered using both documents. FSB physical page 59 supports intermediate decisions/steps escalated to human overseers and their outcome; HKMA physical page 5 supplies optional prompts/reasoning-evidence examples for material outputs where applicable. Historical B review accepted core correctness and full quote support.

Exercises: joint tail selection, eight distinct chunks, multi-part planning, final generation and cross-document citations. Presenter should verify **both** official links/pages, source versions, exact quotations attached to each claim and the optional/applicability wording. Risks: omitted part, selecting an adjacent passage, treating optional records as mandatory, or claims exceeding their own quotes.

### C. Insufficient evidence: EXP-R07

**Question:** In the FSB's 2026 investment risk assessment case study, what output does the AI produce, and what is the internal portfolio identifier used in the first assessment?

Historical expected behavior: whole-question refusal. The retrieved text can support the structured initial risk assessment, but does not provide the internal portfolio identifier. Historical review accepted refusal.

Exercises: retrieval plus unsupported-part planning, refusal propagation and UI without fabricated identifiers/citations. Presenter should confirm the application does not answer just the supported half, invent an identifier or call final generation after an unsupported plan. Risk: a mistaken supported flag could trigger a second request or an unsupported answer; stop and record that first result rather than retrying for a nicer one.

### Request/budget boundary

Expected requests: **2 + 2 + 1 = 5**. Conservative maximum for three submissions: **6 requests**, because a mistaken plan on the refusal case could reach stage two. Maximum configured output allocation: **7,200 tokens** across six requests; input tokens and account fees are additional, so this is **not a monetary cap**. Worst-case configured request deadlines sum to 720 seconds if all six calls reach their deadline, plus local work. No paid-price estimate is asserted or checked here.

Before execution, obtain explicit approval for the three questions/provider, maximum six attempts and a monetary ceiling. The operator should configure the real key locally without sharing it, verify account limits and an isolated copy of the reproduced index, and restart the normal application without this offline harness. Run only the three agreed submissions. Stop on provider/audit/citation failure or budget exhaustion; do not auto-retry or rewrite historical records. Save new acceptance observations under a new non-frozen name and review every source/quote manually.

## 9. Remaining steps before final submission

1. Team members inspect this report, the first-failure logs and the proposed live scope. Approve a live budget separately if desired; do not confuse this report with trial execution consent.
2. On the presentation machine, use the combined app environment, copy/reproduce the same five-document index/cache, verify hashes, select the intended profile and check PDF page-link behavior. Do not expand the dataset or silently adjust pinned checksums.
3. If separately authorized, run the three limited live submissions above and retain first responses/failures, provider usage and source screenshots as **new acceptance evidence**, not replacements for the frozen full40 results.
4. Human review must check every substantive claim against its own exact quotes and source conditions. Present EXP28/EXP05 openly as limitations; retain the development-regression qualification on all historical metrics.
5. Review the report as the sole pending repository change. Commit/push/release tagging and any accounting fix require separate explicit approval. GitHub CI remains absent and should not be described as passing.

**Final verdict: READY WITH DOCUMENTED LIMITATIONS.** Offline integration acceptance is complete. Limited live-provider acceptance is recommended only after separate authorization; no live API call or new charge was incurred.
