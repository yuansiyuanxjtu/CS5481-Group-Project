"""Evaluation checkpoints, provenance and no fabricated accuracy."""
from dataclasses import replace
import json

import pytest

from rag_app.config import Settings
from rag_app.evaluation import load_questions, metrics, run_evaluation


@pytest.fixture
def inputs(tmp_path):
    gold, ood = tmp_path / "gold.jsonl", tmp_path / "ood.jsonl"
    gold.write_text("\n".join(json.dumps({"id": f"T{i}", "question": "Synthetic question?",
        "reference_answer": "Synthetic answer", "evidence": [{"document_id": "fictional", "page_start": 1, "page_end": 1}]}) for i in range(20)))
    ood.write_text("\n".join(json.dumps({"id": f"O{i}", "question": "Synthetic outside question?",
        "reference_answer": "No evidence"}) for i in range(5)))
    (tmp_path / "benchmark.json").write_text("{}")
    (tmp_path / "temporal_catalog.json").write_text("{}")
    return tmp_path, gold, ood


def test_question_counts_and_duplicate_ids(inputs):
    folder, gold, ood = inputs
    assert len(load_questions(gold, ood)) == 25
    ood.write_text(ood.read_text().replace('"O0"', '"T0"'))
    with pytest.raises(ValueError, match="unique"):
        load_questions(gold, ood)


def test_failure_stops_requests_and_checkpoints_without_secrets(inputs):
    folder, gold, ood = inputs
    class FakeService:
        settings = replace(Settings(), api_key="SYNTHETIC_SECRET_DO_NOT_SAVE", experiment_dir=folder)
        calls = 0
        def answer_question(self, question):
            self.calls += 1
            return {"status": "llm_error", "answer": "", "citations": [], "error": "Test-only failure"}
    service = FakeService()
    output = folder / "run.json"
    result = run_evaluation(service, gold, ood, output)
    assert service.calls == 1 and len(result["records"]) == 25
    assert result["records"][1]["result"]["status"] == "not_run"
    assert "SYNTHETIC_SECRET" not in output.read_text()
    assert (folder / "run_ratings.csv").is_file()
    assert b"\r\n" not in (folder / "run_ratings.csv").read_bytes()
    with pytest.raises(FileExistsError):
        run_evaluation(service, gold, ood, output)


def test_invalid_human_ratings_rejected():
    records = [{"id": "g", "answerable": True, "result": {"status": "insufficient_evidence"}},
               {"id": "o", "answerable": False, "result": {"status": "answered"}}]
    ratings = {key: {"verdict": "correct", "citation_verdict": "valid", "reason": "Test", "reviewer": "Test"} for key in ("g", "o")}
    with pytest.raises(ValueError, match="refusal"):
        metrics(records, ratings)
    ratings["g"]["verdict"] = "incorrect"
    with pytest.raises(ValueError, match="OOD"):
        metrics(records, ratings)
    ratings["o"]["verdict"] = "incorrect"
    ratings["o"]["citation_verdict"] = "not_applicable"
    with pytest.raises(ValueError, match="citation assessment"):
        metrics(records, ratings)


def test_resume_retains_completed_answers_and_retries_only_failures(inputs):
    folder, gold, ood = inputs
    class FakeService:
        settings = replace(Settings(), api_key="TEST_ONLY", experiment_dir=folder)
        calls = 0
        def answer_question(self, question):
            self.calls += 1
            status = "insufficient_evidence" if self.calls == 1 else "llm_error"
            return {"status": status, "answer": "", "citations": [], "error": None}
    first = FakeService()
    original = folder / "original.json"
    run_evaluation(first, gold, ood, original)
    first_bytes = original.read_bytes()
    second = FakeService()
    second.settings = replace(second.settings, timeout=60)
    result = run_evaluation(second, gold, ood, folder / "resumed.json", resume=original)
    assert result["resume"]["retained_ids"] == ["T0"]
    assert result["records"][0]["request_timeout_seconds"] == 30
    assert original.read_bytes() == first_bytes
    assert second.calls == 2  # one refusal then a service failure
    second.settings = replace(second.settings, model="changed-model")
    with pytest.raises(ValueError, match="requested_model"):
        run_evaluation(second, gold, ood, folder / "wrong.json", resume=original)
