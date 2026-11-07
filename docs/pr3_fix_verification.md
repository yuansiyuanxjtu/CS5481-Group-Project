# PR #3 targeted fixes and verification

Date: 7 November 2026 (Asia/Hong_Kong). Base: `a7f7084b657ccf341fabf333291e432ffb0b04e6` (`feature/retrieval`). All changes remain uncommitted in an isolated worktree. No merge, push, force-push, reset, main edit or PR #4 change was performed.

## P1 root cause and fix

The old gate checked the trial ID, 80-attempt allowance and runtime/launcher hashes, but its restart ledger was scoped only by the CLI's freely chosen trial root. One unchanged approval could therefore start the same trial twice at different roots.

The current launcher and direct authorized `run_trial` both call the same validation with the requested root. The approval must explicitly store `authorized_trial_root`, an absolute canonical path; caller-relative paths and symlink aliases are resolved and compared with it. Mismatches are rejected before initialization, credential loading, transport construction, directory creation or request dispatch. The resolved root is then used for the existing exclusive marker. The 80-attempt cap, duplicate tracking, checkpoint/audit behavior and same-root replay protection remain unchanged. Offline preflight with explicitly injected transports and `authorization=None` remains available.

Approvals themselves may not contain relative/symlink aliases, since an alias could be retargeted after approval. A new physical root requires a separate explicit authorization. The shipped example is still `approved: false` with a null root. No real authorization was generated, modified or approved.

## Historical provenance and hash dependencies

`history/runtime_v1` contains byte-for-byte source text snapshots of the old controller/launcher, original runtime manifest and original unapproved example. The original manifest remains SHA-256 `c23200a1ce27c442a21cbe676d10dc87bb230e54ef306bfa3ec057111b0601b5`, matching the untouched historical freeze provenance. Its controller comes from the archived text; its other ten runtime files remain byte-identical in the current tree. A regression verifies all entries and the original launcher fingerprint.

The current manifest is explicitly `canonical-root-bound-v2`, with the patched controller hash. The current unapproved template pins the new manifest and launcher. Historical scores, source evidence, result hashes, raw-execution fingerprints, prompts and retrieval locks were not rewritten or attributed to v2. All twenty joint_pairs8 code/input lock entries remain valid.

## P3 documentation

The preserved `passage_rerank.py` and `all_question_retrieval.py` standalone mains are now explicitly documented as archived exploratory CLIs whose historical inputs are unavailable. Their importable classes remain in the candidate dependency chain. The supported forty-context reproduction entry is `experiments/joint_pairs8/verify_replay.py`. No retrieval algorithm, prompt, missing data or experimental result was changed or invented.

## Regression coverage

The launcher file now has **14 tests** (nine additional tests and strengthened existing assertions). Coverage includes:

- Matching canonical root accepted by launcher and direct call; 80 synthetic dispatches.
- Reusing those exact approval bytes with a different root blocked before credentials/transports/files.
- Missing/invalid roots, relative approval roots and stale runtime/launcher fingerprints rejected.
- Requested relative paths normalized; requested symlink aliases accepted against the canonical root, while symlink aliases in approval fields are rejected.
- Same-root replay and changed output filenames blocked; prior output bytes unchanged.
- A separately authorized second root accepted without a false global lockout.
- Original v1 provenance and current unapproved-template fingerprints verified.

All synthetic approvals state that they are test-only. Tests use MockTransport exclusively; external networking and provider credentials were blocked/removed by the verification runner.

## Actual commands and outcomes

Run from the isolated checkout with the existing combined app environment and cached model. Set:

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0
export PYTHONPATH="$PWD/src:$PWD/experiments/retrieval_candidates"
```

| Command/check | Actual result |
| --- | --- |
| Original v1 launcher replay with one approval, two roots, synthetic transport | Reproduced **80 + 80** dispatches; the negative safety assertion intentionally failed (exit 1). |
| Patched launcher proof with one root-bound approval | First root: **80** mock dispatches. Second root: **0** additional dispatches, credential loads, transport constructions or directories; exit 0. |
| `.venv/bin/python -m pytest -q -p no:cacheprovider experiments/generative40/test_authorized_launcher.py` | **14 passed** on first execution. |
| `.venv/bin/python -m pytest -q -p no:cacheprovider experiments` | **17 passed** on first execution. |
| `.venv/bin/python -m pytest -q -p no:cacheprovider` | **137 passed** on first execution, real-model smoke enabled. |
| `.venv/bin/python -m pytest -q -p no:cacheprovider tests experiments` in the delivered worktree | **154 passed**, 57 existing dependency deprecation warnings; no skipped tests. |
| Preflight below, current worktree | **30 checks passed**, 80 main-trial mock dispatches, 360 stage events, no credentials or actual provider requests. |
| Frozen retrieval replay below, copied index | **40 contexts / 320 evidence blocks verified**; maximum distance difference `2.72e-07`. |

```bash
.venv/bin/python experiments/generative40/preflight_controller80.py --runtime experiments/generative40/runtime --app-src src --output tmp/pr3_preflight_NEW
.venv/bin/python experiments/joint_pairs8/verify_replay.py --experiment-dir ISOLATED_INDEX_COPY --cache-dir .cache/huggingface/hub
```

Use a new preflight output path and a copy of the existing reproduced index. No experimental database was deleted or rebuilt. Full commands, exit codes and logs are retained in the companion verification artifact. The first patched-proof helper invocation used the wrong relative script path and exited 2 before executing any code; the corrected absolute-path invocation passed. That failed command is retained alongside its correction. No repository, experiment, preflight or replay failure was hidden by a retry. The expected original-v1 negative assertion is also retained.

## Files changed

- Gate: `runtime/controller80.py`, `run_authorized_full40.py`.
- Current fingerprints/template: `runtime/runtime_manifest.json`, `authorization.example.json`.
- Regression tests: `test_authorized_launcher.py`.
- Provenance snapshots/readme: `history/runtime_v1/` (five files).
- Guidance: `experiments/generative40/README.md`, `experiments/retrieval_candidates/README.md`, and this report.

The first six paths above are relative to `experiments/generative40/` where applicable. No historical report/score record or joint_pairs8 input, algorithm or LLM prompt is modified.

## Remaining limits and recommendation

The gate assumes the local filesystem/approval record is controlled by the authorized operator. Deleting/moving the trial ledger or malicious concurrent filesystem changes are outside its protection. Windows symlink permissions and other OS/filesystem behaviors were not newly verified; all symlink tests ran without skips on macOS arm64/Python 3.11.15. Existing HNSW intermittency was not observed in these runs. Cloud weights and semantic grading remain subject to the previously documented experimental limits; no new answer-accuracy claim is made.

Both requested findings are resolved in the verified local patch. Remote PR #3 is still at the original commit because commit/push was not authorized. Publish these fixes only after approval, then merge the patched head rather than the unpatched remote head. Preserve `feature/retrieval`, which remains PR #4's base.

READY TO MERGE WITH DOCUMENTED LIMITATIONS — after the verified fixes are published to PR #3.
