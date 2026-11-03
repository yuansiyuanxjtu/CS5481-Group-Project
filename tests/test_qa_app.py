"""Five explicitly synthetic chunks exercise C without paid calls or corpus fabrication."""
from dataclasses import replace
import json

import httpx
import pytest

from rag_app.config import Settings
from rag_app.evaluation import metrics
from rag_app.grounding import prepare_evidence
from rag_app.llm import ChatClient, GenerationError, LLMError
from rag_app.service import QAService


@pytest.fixture
def fixture_data():
    hits = [{"chunk_id": f"test_p{i}_c1", "document_id": f"test{i}",
             "text": f"Fictional test rule {i}: the sample board remains accountable for the test system.",
             "source_url": f"https://example.invalid/test{i}.pdf", "page_number": i,
             "distance": 0.1 * i} for i in range(1, 6)]
    catalog = {h["document_id"]: {"title": "Synthetic test only", "source_pdf_url": h["source_url"],
                "publication_date": "2020-01-01", "regulatory_status": "unknown"} for h in hits}
    return hits, catalog


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def retrieve(self, *args, **kwargs):
        return self.hits


class FakeLLM:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def generate(self, messages):
        self.calls += 1
        self.messages = messages
        return {"content": json.dumps(self.payload), "model": "test-only", "usage": {}}


def valid_payload(ids=(1,)):
    return {"status": "answered", "claims": [{"text": "The sample board remains accountable.",
             "evidence": [{"id": i, "quote": "the sample board remains accountable"} for i in ids]}]}


def make_service(fixture_data, payload=None, cfg=None):
    hits, catalog = fixture_data
    return QAService(FakeRetriever(hits), FakeLLM(payload or valid_payload()), catalog, cfg or Settings())


def test_answer_uses_real_mapping_and_multiple_sources(fixture_data):
    result = make_service(fixture_data, valid_payload((1, 2))).answer_question("Who is accountable?")
    assert result["status"] == "answered"
    assert result["answer"].endswith("[1][2]")
    assert [c["page_number"] for c in result["citations"]] == [1, 2]
    assert result["citations"][0]["page_url"] == "https://example.invalid/test1.pdf#page=1"


@pytest.mark.parametrize("bad", [
    {"id": 9, "quote": "the sample board remains accountable"},
    {"id": True, "quote": "the sample board remains accountable"},
    {"id": 1, "quote": "Invented quote not in any source"},
    {"id": 1, "quote": "a"},
])
def test_invalid_citations_fail_closed(fixture_data, bad):
    payload = valid_payload()
    payload["claims"][0]["evidence"] = [bad]
    result = make_service(fixture_data, payload).answer_question("Test question")
    assert result["status"] == "invalid_output" and not result["citations"] and not result["answer"]


@pytest.mark.parametrize("text", ["Answer [9]", "See https://example.invalid", "<script>x</script>"])
def test_model_cannot_supply_its_own_links_or_ids(fixture_data, text):
    payload = valid_payload()
    payload["claims"][0]["text"] = text
    assert make_service(fixture_data, payload).answer_question("Test")["status"] == "invalid_output"


def test_missing_citation_rejected(fixture_data):
    payload = valid_payload()
    payload["claims"][0]["evidence"] = []
    assert make_service(fixture_data, payload).answer_question("Test")["status"] == "invalid_output"


def test_empty_retrieval_skips_llm_and_refuses(fixture_data):
    svc = make_service(fixture_data)
    svc.retriever.hits = []
    result = svc.answer_question("Outside question")
    assert result["status"] == "insufficient_evidence" and svc.llm.calls == 0


def test_ood_or_conflicting_evidence_refusal(fixture_data):
    result = make_service(fixture_data, {"status": "insufficient_evidence", "claims": []}).answer_question("Conflicting question")
    assert result["status"] == "insufficient_evidence" and result["citations"] == []


def test_historical_and_unknown_status_preserved_in_prompt_and_citations(fixture_data):
    fixture_data[1]["test1"]["regulatory_status"] = "superseded"
    fixture_data[1]["test1"]["status_evidence"] = {"url": "https://example.invalid/new.pdf", "locator": "test"}
    svc = make_service(fixture_data, valid_payload((1, 2)))
    result = svc.answer_question("Compare historical rules")
    assert [c["regulatory_status"] for c in result["citations"]] == ["superseded", "unknown"]
    context = json.loads(svc.llm.messages[1]["content"])
    assert context["evidence"][0]["status_evidence"]["locator"] == "test"


@pytest.mark.parametrize("mutation", [{"page_number": 0}, {"page_number": True},
    {"source_url": "https://wrong.invalid/a.pdf"}, {"distance": float("nan")}, {"text": ""}])
def test_bad_retrieval_metadata_is_an_error_not_a_refusal(fixture_data, mutation):
    fixture_data[0][0].update(mutation)
    assert make_service(fixture_data).answer_question("Test")["status"] == "retrieval_error"


def test_retrieval_failure_distinct_from_no_answer(fixture_data):
    svc = make_service(fixture_data)
    def fail(*args, **kwargs):
        raise FileNotFoundError("sensitive path")
    svc.retriever.retrieve = fail
    result = svc.answer_question("Test")
    assert result["status"] == "retrieval_error" and "sensitive" not in result["error"]


def test_cutoff_renumbers_evidence(fixture_data):
    svc = make_service(fixture_data, cfg=replace(Settings(), max_distance=0.15))
    result = svc.answer_question("Test")
    assert result["status"] == "answered" and len(result["retrieved"]) == 1


@pytest.mark.parametrize("question", ["", "  ", None, "x" * 2001])
def test_invalid_input_does_not_call_llm(fixture_data, question):
    svc = make_service(fixture_data)
    assert svc.answer_question(question)["status"] == "invalid_input" and svc.llm.calls == 0


def test_llm_payload_and_safe_config():
    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "test-model" and body["thinking"] == {"type": "disabled"}
        assert body["max_tokens"] == 1200 and body["response_format"]["type"] == "json_object"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "model": "test-model"})
    cfg = Settings(api_key="SECRET_TEST_ONLY", model="test-model", thinking="disabled")
    assert "SECRET" not in repr(cfg)
    assert ChatClient(cfg, httpx.MockTransport(respond)).generate([])["model"] == "test-model"


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_http_errors_do_not_leak_provider_body(status):
    client = ChatClient(Settings(api_key="TEST_ONLY"), httpx.MockTransport(
        lambda req: httpx.Response(status, text="sensitive-provider-body")))
    with pytest.raises(LLMError) as exc:
        client.generate([])
    assert "sensitive" not in str(exc.value)


def test_timeout_and_malformed_or_truncated_response():
    def timeout(req):
        raise httpx.ReadTimeout("secret test")
    with pytest.raises(LLMError, match="timed out"):
        ChatClient(Settings(api_key="TEST"), httpx.MockTransport(timeout)).generate([])
    for body in ({}, {"choices": [{"finish_reason": "length"}]}):
        with pytest.raises(GenerationError):
            ChatClient(Settings(api_key="TEST"), httpx.MockTransport(lambda req: httpx.Response(200, json=body))).generate([])


def test_missing_key_is_configuration_error():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        ChatClient(Settings()).generate([])


def test_total_deadline_cancels_a_live_provider_request():
    import asyncio
    cancelled = []
    async def slow(request):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    with pytest.raises(LLMError, match="total time limit"):
        ChatClient(Settings(api_key="TEST", timeout=1), httpx.MockTransport(slow)).generate([])
    assert cancelled == [True]


def test_evaluation_denominator_and_pending_scores():
    records = [{"id": "q1", "answerable": True, "result": {"status": "answered"}},
               {"id": "q2", "answerable": True, "result": {"status": "llm_error"}},
               {"id": "o1", "answerable": False, "result": {"status": "insufficient_evidence"}}]
    ratings = {r["id"]: {"verdict": "pending", "citation_verdict": "pending", "reason": "", "reviewer": ""} for r in records}
    assert metrics(records, ratings)["strict_accuracy"] is None
    for key in ratings:
        ratings[key].update(verdict="correct" if key != "q2" else "incorrect", citation_verdict="valid", reason="Test judgment", reviewer="test")
    result = metrics(records, ratings)
    assert result["strict_accuracy"] == 0.5 and result["ood_explicit_refusal_rate"] == 1
    ratings["q2"]["verdict"] = "correct"
    with pytest.raises(ValueError):
        metrics(records, ratings)
