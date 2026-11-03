# Final C experiment: direct DeepSeek API

Evaluated 2026-11-03, Asia/Hong_Kong. These results use the official provider, not the
earlier school gateway. Ratings are **Codex source-reviewed draft judgments**, pending
independent human confirmation by a group member. No human reviewer or signature is fabricated.

## Setup and results

| Item | Value |
| --- | --- |
| Provider / returned API model ID | `https://api.deepseek.com` / `deepseek-flash` |
| Retrieval | B's unchanged `enhanced`, `fixed_150`, Top-5 |
| Corpus / embedding | Same five checksum-pinned PDFs; pinned MiniLM |
| Questions | B's unchanged 24 gold QA + C's five OOD questions |
| Generation | JSON output; temperature 0; thinking disabled; max 1,200 output tokens |
| Gold answers graded correct / partial / incorrect | 8 / 3 / 13 |
| Strict answer accuracy | **8/24 = 33.33%** |
| Optional partial-credit score | **(8 + 0.5×3)/24 = 39.58%** |
| OOD explicit refusal | **5/5 = 100%** on this small set |
| Service failures in completed run | 0 |
| Invalid citation IDs or fabricated quotation strings accepted | 0 observed |
| Automated PDF source checks | **56/56 passed**: 27 gold locators + 29 answer quotations |

`answer_evaluation_official.json` preserves the first official attempt: B01-B20 completed,
B21 timed out at 60 seconds, and subsequent questions were not run. The linked continuation
`answer_evaluation_official_completed.json` retains B01-B20 unchanged and completes only
the failed/unrun questions with a 120-second network timeout. Nothing was resampled to
replace an incorrect, partial or refused answer. The resulting 29 question outcomes used
55,542 total provider-reported tokens, excluding the failed attempt and separate smoke/demo calls.

The 24 gold questions produced 11 answers and 13 refusals. All 13 refusals are incorrect
for end-to-end gold-answer correctness, even when they are sensible given missing context.
The five OOD questions all produced explicit refusal with no citations. API failures are
never counted as successful refusals. The draft grading rationale for every question is
in `answer_evaluation_official_completed_ratings.csv`; raw answers, chunks, quotations,
source IDs, URLs, physical pages and run fingerprints are in the completed JSON.

The dominant limit is evidence retrieval. B's existing page-level Hit@5 for this default
configuration was 45.83% on its Windows run. Page hits do not guarantee the needed text
is in the selected chunk. This is a context for interpreting the results, not a direct
cross-platform replication of B's timing or an assertion that retrieval hit rate and
answer correctness are the same metric. No accuracy target was assumed or hidden by
discarding difficult questions.

## Actual errors and lessons

| Case | Observed answer / evidence | Draft judgment | Interpretation |
| --- | --- | --- | --- |
| B02 | Refuses the four-dimension question; 2019 physical page 2 is absent from Top-5 | Incorrect | The generator cannot recover missing source evidence. |
| B08 | Quotes shadow-AI restrictions but omits maintaining the approved-use-case inventory | Partial | Correct provenance does not ensure completeness; the right page contains multiple chunks. |
| B15 | Quotes intended-use discussion from FSB page 8 but omits non-prescriptive/non-binding characterization | Partial | The model should have refused or made the missing part explicit; retrieved real quotations alone are insufficient. |
| B16 | Retrieves FSB physical page 8 chunks, but not the proportional-application paragraph | Incorrect refusal | Another page-level hit versus text-level evidence gap. |
| B23 | Refuses the historical/newer cross-document comparison | Incorrect | Complete two-source evidence is missing; no claim of robust multi-document answering is warranted. |
| B24 | Names the correct FSB report and date from the HKMA footnote but omits the binding-nature part | Partial | The answer does not cite the second requested document. It is not a successful complete cross-document answer. |

Successful source-backed cases include B05 (historical suspension/fallback), B06
(supersession), B07 (ART), B09 (human oversight), B17 (assessment timing), B18
(verification versus validation), and B21/B22 (BIS table facts).

No invalid citation IDs or fabricated quote strings appeared in accepted real outputs.
Tests explicitly inject nonexistent IDs, missing citations and invented quotations and
verify fail-closed behavior. Those are synthetic tests, not claimed real model errors.
The substring checks prove source membership and physical-page provenance only; they
do not prove semantic entailment, completeness or zero hallucination. The 5/5 OOD rate
also does not establish general out-of-domain robustness.

## Demo and reproduction

`demo_records.json` is a **separate real six-question run**, covering single-document
B02, historical B05, supersession B06, cross-document B23/B24 and OOD01. Its outcomes
are 2 answers and 4 refusals. This deliberately exposes retrieval failures rather than
presenting the cross-document scenarios as successful. B24's refusal in the demo differs
from its partial answer in the formal run: temperature 0 is not a guarantee of identical
provider output. Do not replace the formal result with the nicer demo behavior.

Screenshots under `docs/demo/` show real answers, exact quotations, official links and
physical page labels. New reruns must choose fresh filenames:

```bash
.venv/bin/python scripts/eval_answers.py run --output docs/answer_evaluation_new.json
.venv/bin/python scripts/check_answer_sources.py \
  --run docs/answer_evaluation_new.json --output docs/answer_sources_new.json
# Fill the new ratings CSV with reviewer, reason and citation assessment, then:
.venv/bin/python scripts/eval_answers.py summarize \
  --run docs/answer_evaluation_new.json --ratings docs/answer_evaluation_new_ratings.csv \
  --output docs/answer_summary_new.json
```

Next team review: manually confirm the gold references and draft answer grades; agree
with B on the retrieval configuration (its 150/30 configuration is stronger in B's existing
experiment); investigate evidence completeness on separate development questions. Do
not change the test set, delete refusals or retune repeatedly on the final QA to inflate scores.
