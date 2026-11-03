"""Streamlit interaction checks using synthetic service results only."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from rag_app import service

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def clear_resources():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_initial_page_and_blank_submission(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception and app.title[0].value == "Knowledge Base Q&A"
    app.button[0].click().run()
    assert app.warning[0].value == "Enter a question first."


def test_missing_key_has_useful_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    app = AppTest.from_file(str(APP)).run()
    app.text_area[0].set_value("A test question")
    app.button[0].click().run()
    assert not app.exception and "LLM_API_KEY" in app.error[0].value


@pytest.mark.parametrize("status", ["answered", "insufficient_evidence", "retrieval_error", "llm_error", "invalid_output"])
def test_result_states_render(monkeypatch, status):
    monkeypatch.setenv("LLM_API_KEY", "synthetic-test-key")
    citation = {"evidence_id": 1, "title": "Synthetic test publication", "publication_date": "2020-01-01",
                "page_number": 2, "regulatory_status": "superseded", "page_url": "https://example.invalid/test.pdf#page=2",
                "source_url": "https://example.invalid/test.pdf", "document_id": "test", "chunk_id": "test_p2_c1",
                "excerpts": ["Synthetic supporting quotation."]}
    result = {"status": status, "answer": "Synthetic answer [1].", "citations": [citation] if status == "answered" else [],
              "retrieved": [], "error": "Synthetic service error", "elapsed_seconds": 0.1}
    class FakeService:
        def answer_question(self, question):
            return result
    monkeypatch.setattr(service, "create_service", lambda cfg: FakeService())
    app = AppTest.from_file(str(APP)).run()
    app.text_area[0].set_value("Synthetic question")
    app.button[0].click().run()
    assert not app.exception
    if status == "answered":
        assert any("Synthetic answer" in item.value for item in app.text)
        assert any("superseded" in item.value for item in app.warning)
        assert len(app.get("link_button")) == 1
    elif status == "insufficient_evidence":
        assert len(app.info) == 1 and not app.error
    else:
        assert app.error[0].value == "Synthetic service error"
