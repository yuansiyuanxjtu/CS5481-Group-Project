# Frozen full40 evidence-plan experiment

This directory preserves the evaluated candidate separately from the default
application. It uses the same forty questions and 320 ordered evidence records as
the existing `source_neighbor8` baseline. It does not rerun retrieval or alter the
ingestion output, persistent index, default prompt or Streamlit application.

The candidate asks a model to select evidence for every question part, refuses the
whole question if any part lacks support, otherwise asks the model to generate the
final answer, then applies the original citation validator. The deterministic
quotation preview is auxiliary and does not replace final model-generated prose.

## Reviewed result

| Fixed-denominator metric | Existing complete40 baseline | Candidate |
| --- | --- | --- |
| Complete core answer | 27/30 | 27/30 |
| Complete answer with every claim supported | 24/30 | 25/30 |
| Expected refusal | 7/10 | 10/10 |

The independent first-response trial used 69 provider calls (40 selection and 29
answer generation), with 405,327 reported tokens. All 69 responses were HTTP200.
Citation support gained EXP08/EXP27 and lost EXP05; refusal gained EXP-R06/07/08.
EXP20 retains a quotation-scope gap. EXP28/EXP30 are answerable cases that refused;
EXP29 remains partial. Core accuracy did not improve. Read the [full report](../../docs/experiments/generative40/report.md)
and [paired comparison](../../docs/experiments/generative40/paired_comparison.json).

This is an exposed development/regression set, not an unseen test or an equal-cost
ablation. Earlier 12-case and four-case trials remain separate and were not mixed
into the complete40 result. Human QA signoff remains pending.

## Execution version separation

The original measured runtime is retained by byte-for-byte controller/launcher source snapshots and its original manifest/unapproved template in [history/runtime_v1](history/runtime_v1/README.md). The other ten runtime files, model inputs, prompts, evaluator data, historical result hashes and scores remain unchanged. The historical manifest is still the one identified by `docs/experiments/generative40/freeze_provenance.json`.

The current controller is `canonical-root-bound-v2`: it fixes approval replay through a different trial root. Its manifest pins the patched controller, and the current unapproved template pins that manifest and the current launcher. This current execution gate is not retrospectively attributed to the historical full40 results. The joint_pairs8 retrieval/input lock does not depend on the controller or launcher and remains unchanged.

## Layout and frozen bytes

- `runtime/`: bounded controller, original method with only 24-to-80 call-cap
  substitutions, prompts, catalog and input-only forty-message snapshot. Its
  manifest verifies the executable/input bytes and the six original application
  source hashes before execution.
- `evaluator/`: references, historical baseline judgments and scoring rubric;
  these files must never enter a model request.
- `preflight_controller80.py`: offline transport-injected orchestration checks.
- `run_authorized_full40.py`: explicit version-bound authorization gate for any
  separately approved future run.
- `authorization.example.json`: deliberately unapproved; historical consent is
  not distributed and cannot authorize another experiment.

The scoped `.gitattributes` rules preserve LF bytes so manifests also work after
a Windows checkout. No PDF, model cache, vector database, original credential,
provider HTTP log or checkpoint is committed. Frozen public-source excerpts and
reviewed per-case summaries are included for reproducibility. Original full
responses/logs remain local and are referenced by SHA256 in the report provenance.

## Run the free preflight

From the repository root, use the existing environment with the app dependencies
documented in `docs/member_c_handoff.md`. No dataset/model download is required for
this frozen-input preflight. On Windows:

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Resolve-Path 'src').Path
.venv/Scripts/python.exe experiments/generative40/preflight_controller80.py --runtime experiments/generative40/runtime --app-src src --output tmp/full40_preflight
.venv/Scripts/python.exe -m unittest discover -s experiments/generative40 -p test_authorized_launcher.py -v
.venv/Scripts/python.exe -m pytest experiments/retrieval_candidates/test_budget_retrieval.py -q
```

Use a new preflight output directory if it already exists. POSIX uses the same
script arguments with `.venv/bin/python` and `PYTHONPATH=src`. The 30
orchestration checks exercise 80 mock dispatches, the 81st-call block, duplicate and
renamed-output restart guards, unsupported-part skipping, both-stage failures,
audit persistence failures and usage. Additional launcher regressions cover canonical-root binding, alias normalization, same-root replay, fresh separately authorized roots, historical provenance and truthful formal-mode metadata with synthetic transports only.

Preflight forbids credential/evaluator reads and real provider transports. Windows
allows only CPython's internal loopback socketpair required by asyncio. The
exclusive trial marker is flushed/fsynced on Windows; directory fsync is retained
on supporting systems. No guarantee is made for total disk loss. Unknown delivery
or audit failure never triggers automatic resend/recovery.

## Any future real run

The 69-call historical trial is complete. Do not reuse its unused allowance or
historical approval. The published authorization example is false and rejects
before loading credentials. A future run needs a new user-approved trial ID,
matching runtime/launcher hashes, a fixed trial-root and a newly agreed scope/cost.

A real approval must contain `authorized_trial_root` as the exact **absolute canonical path** approved by the user, as well as the current trial/runtime/launcher fingerprints and 80-attempt limit. The shipped value is null and `approved` remains false. No helper fills, changes or approves real consent. Relative paths or symlink aliases may be supplied as the requested `--trial-root`; both launcher and direct authorized `run_trial` calls resolve that request and compare it with the fixed canonical path in the approval before credentials, transport construction or trial files. Approval fields that are missing, relative, or symlink aliases are rejected. Preflight with `authorization=None` remains an explicitly transport-injected offline path; it is not authorization for provider traffic.

Changing only `--trial-root` cannot reuse an approval. A different root requires separate explicit approval. Same-root restarts, including a changed output filename or a symlink alias, still hit the original exclusive trial marker. Preserve that marker and the trial directory; deleting/moving ledgers or concurrently changing filesystem ownership/symlinks is outside this local guard's trust boundary.

After such approval, the explicit launcher takes `--runtime`, `--app-src`,
`--trial-root` and `--approval-file`. Provider credentials stay in the local
environment. The launcher checks authorization first, validates frozen settings,
and supplies a transport with retries=0. Stop on infrastructure/audit faults; keep
the first response and all failed/not-run cases in their fixed denominators.

## Evidence gaps are diagnoses, not repaired retrieval

See [offline evidence completeness](../../docs/experiments/generative40/evidence_completeness.md).
The missing passages for EXP28/29/30 exist in processed chunks; they were not
selected into the eight-block context. SQLite text/metadata inspection did not
replay vector/ANN ranking. No new retrieval fix or accuracy improvement is claimed.
The preserved [retrieval candidate](../retrieval_candidates/README.md) is the
starting point for a separately versioned, offline, fixed-budget investigation.
