# Archived school-gateway evaluation: partial real run

This file describes the earlier school-gateway attempt only. The replacement direct
DeepSeek experiment is recorded separately in `answer_evaluation_official.json` and its
associated analysis. Do not merge the providers' outputs into a single accuracy score.

School-run status on 2026-11-03 (Asia/Hong_Kong): application implementation is complete and real
grounded answers work, but **C's full acceptance is not complete**. The school gateway
became unavailable during evaluation. No full accuracy or OOD refusal percentage is
claimed. The current ratings are Codex source-reviewed draft judgments, pending a group
member's human confirmation; they must not be called independent human verification.

## Frozen experiment and actual outcomes

- Provider: school LiteLLM, `https://llm.cs.cityu.edu.hk/v1`.
- API model ID: `CS5351/DeepSeek-V4-Flash`, confirmed by authenticated model listing.
- B interface: enhanced cleaning, `fixed_150`, Top-5, pinned MiniLM.
- B's unchanged shared 24 gold questions plus C's five OOD questions.
- Prompt `c-grounded-1`, temperature 0, max output 1,200 tokens, JSON output.
- First request timeout 30 seconds; resumed requests 60 seconds. Configuration changes
  affect network tolerance only; no completed answer is resampled for a better score.

Artifacts:

1. `answer_evaluation.json`: first attempt. B01-B15 returned model output; B16 timed out.
2. `answer_evaluation_completed.json`: continuation; retains B01-B15 unchanged, retries
   B16 only, receives HTTP 429, leaves subsequent questions `not_run`.
3. `answer_evaluation_final.json`: subsequent continuation with the same outcome. Despite
   its filename, its contents remain explicitly **incomplete**.
4. `answer_evaluation_final_ratings.csv`: draft source review of executed rows. Unrun
   rows remain pending. Prior-attempt rating templates remain unfilled, not alternative scores.
5. `answer_source_checks_attempt1.json`: all 27 gold excerpts and all 18 accepted answer
   excerpts are present on their checksum-pinned physical PDF pages (45/45 checks).

The 15 returned outputs contain 6 answers and 9 explicit refusals. Draft review finds
4 correct, 2 partial and 9 incorrect false refusals. B16 is a service failure, graded
incorrect in the end-to-end denominator. B17-B24 and all five OOD questions are unrun.
Do not describe refusal on answerable gold questions as a successful OOD result.

The provider diagnostic for HTTP 429 was: `No deployments available for selected model`.
It did not report an invalid credential. The dashboard also failed to load in the test
browser; model-list authentication and several generation requests nevertheless worked.
Private key/account metadata is not included in these artifacts.

## Actual error analysis

| Case | Observation | Failure mechanism | Consequence / next investigation |
| --- | --- | --- | --- |
| B02 | Refuses a gold-answerable question; no 2019 physical page 2 hit | Retrieval miss | Improving generation alone cannot recover the missing list of data-quality dimensions. B should investigate retrieval on a separate development set. |
| B08 | Correctly cites restrictions on shadow AI, but omits maintaining an approved-use-case inventory | Page-level hit lacks required passage; generator answers incompletely | Exact citations can be legitimate while the full answer is partial. All required clauses need evidence. |
| B15 | Cites real page 8 material on use of sound practices but omits the requested non-binding character from page 6 | Partial evidence plus insufficient answerability judgment | Quote membership does not establish completeness or correct question scope. Draft grade partial. |
| B16 | Timeout followed by deployment-unavailable HTTP 429 | External service failure | Preserve failure attempts; distinguish from knowledge refusal and resume only failed/unrun requests. |

Successful checks: B05 uses the superseded 2019 publication and retains its historical
status; B06 cites the explicit supersession sentence on physical page 1; B07 correctly
identifies all ART pillars across two chunks; B09 quotes reviewer competence, information,
time and authority. Source card screenshots are in `docs/demo/`.

## Complete after the school deployment recovers

```bash
.venv/bin/python scripts/eval_answers.py run \
  --resume docs/answer_evaluation_final.json --output docs/answer_evaluation_resumed.json
```

Resuming a school run also requires its original generation-source hashes and school
configuration; restore the matching generation version from commit `2e8b562` in an isolated
checkout first. Current defaults target the official provider and must not be mixed in.
This preserves B01-B15 and retries B16 plus the 13 unrun questions. It does not re-answer
the nine false refusals or two partial answers. Grade the new CSV against the PDFs;
transfer the existing judgments for retained rows and independently review the rest.
When all 29 rows have completed ratings, summarize the new run:

```bash
.venv/bin/python scripts/eval_answers.py summarize \
  --run docs/answer_evaluation_resumed.json \
  --ratings docs/answer_evaluation_resumed_ratings.csv \
  --output docs/answer_summary_completed.json
.venv/bin/python scripts/check_answer_sources.py \
  --run docs/answer_evaluation_resumed.json --output docs/answer_source_checks_completed.json
.venv/bin/python scripts/eval_answers.py run --demo --output docs/demo_records.json
```

Strict correctness is `correct/24`; partial-credit score is `(correct + 0.5*partial)/24`.
Never remove failed questions from the denominator. OOD success requires an explicit
`insufficient_evidence` response, not a timeout or API failure. At present full metrics
remain null. Revisit source entailment, historical versions and cross-document coverage
in the human review; no zero-hallucination claim is supported.
