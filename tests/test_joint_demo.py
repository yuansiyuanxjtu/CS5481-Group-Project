"""Streamlit integration with frozen evidence and injected provider responses."""
from hashlib import sha256
import json
from pathlib import Path

import httpx
import streamlit as st
from streamlit.testing.v1 import AppTest

from rag_app import demo

ROOT = Path(__file__).resolve().parents[1]


def test_joint_profile_two_stage_sources_refusal_and_http_failure(monkeypatch, tmp_path):
    st.cache_resource.clear()
    rows = json.loads((demo.JOINT / "model_inputs40.json").read_bytes())["requests"]
    cases = {r["id"]: json.loads(r["messages"][1]["content"]) for r in rows}
    evidence = {r["question"]: r["evidence"] for r in cases.values()}
    catalog = (demo.RUNTIME / "temporal_catalog.json").read_bytes()
    (tmp_path / "temporal_catalog.json").write_bytes(catalog)
    (tmp_path / "enhanced").mkdir()
    (tmp_path / "enhanced/collection_context.json").write_text(
        json.dumps({"temporal_catalog_sha256": sha256(catalog).hexdigest()}), encoding="utf-8")
    for key, value in {"RAG_DEMO_PROFILE": "joint_pairs8", "RAG_EXPERIMENT_DIR": str(tmp_path),
                       "LLM_API_KEY": "offline-demo-test", "LLM_BASE_URL": "https://api.deepseek.com",
                       "LLM_MODEL": "deepseek-flash"}.items():
        monkeypatch.setenv(key, value)

    candidate, _ = demo._load_experiment()

    class SnapshotRetriever:
        def __init__(self, experiment_dir, cache_dir):
            assert experiment_dir == tmp_path

        def retrieve(self, question, top_k, *, collection, arm):
            assert (top_k, collection, arm) == (8, "fixed_150_overlap_30", "enhanced")
            return evidence[question]

    monkeypatch.setattr(candidate, "JointCandidateRetriever", SnapshotRetriever)
    calls = []
    failure_stage = None

    def provider(request):
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["max_tokens"] == 1200
        assert body["thinking"] == {"type": "disabled"} and body["response_format"] == {"type": "json_object"}
        payload = json.loads(body["messages"][1]["content"])
        question = payload["question"]
        stage = "generation" if "evidence_plan" in payload else "selection"
        calls.append(stage)
        assert payload["evidence"] == evidence[question]
        if stage == failure_stage:
            return httpx.Response(503, text="synthetic provider error")
        if stage == "selection":
            hints = ("The log includes intermediate decisions", "records may also include prompts")
            if question == cases["EXP11"]["question"]:
                hints = ("from a longer-term perspective",)
            missing = question == cases["EXP-R07"]["question"]
            if missing:
                hints = ("structured initial risk assessment",)
            units = [next(u["unit_id"] for u in payload["source_units"] if hint in u["text"]) for hint in hints]
            answer = {"parts": [{"part_id": p["part_id"], "supported": i < len(units),
                                 "unit_ids": units[i:i+1]} for i, p in enumerate(payload["question_parts"])]}
        else:
            assert body["messages"][0]["content"] == (demo.RUNTIME / "generation_prompt.txt").read_text(encoding="utf-8")
            answer = {"status": "answered", "claims": [{"text": unit["text"], "evidence": unit["evidence"]}
                      for unit in payload["evidence_plan"]["selected_units"]]}
        return httpx.Response(200, json={"model": "deepseek-flash", "usage": {"total_tokens": 10},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]})

    factory = demo.create_demo_service
    monkeypatch.setattr(demo, "create_demo_service",
                        lambda cfg, profile: factory(cfg, profile, transport=httpx.MockTransport(provider)))
    app = AppTest.from_file(str(ROOT / "app.py")).run()

    def submit(case):
        calls.clear()
        app.text_area[0].set_value(cases[case]["question"])
        app.button[0].click().run()
        assert not app.exception

    try:
        submit("EXP11")
        assert calls == ["selection", "generation"] and len(app.get("link_button")) == 1
        assert app.session_state["qa_result"]["usage"]["total_tokens"] == 20
        for _ in range(2):
            submit("EXP30")
            assert calls == ["selection", "generation"] and len(app.get("link_button")) == 2
            assert {c["page_number"] for c in app.session_state["qa_result"]["citations"]} == {5, 59}
        submit("EXP-R07")
        assert calls == ["selection"] and len(app.info) == 1 and not app.error
        assert app.session_state["qa_result"]["usage"]["total_tokens"] == 10
        for failure_stage in ("selection", "generation"):
            submit("EXP30")
            expected = ["selection"] if failure_stage == "selection" else ["selection", "generation"]
            assert calls == expected and app.error and not app.info and not app.get("link_button")
            assert app.session_state["qa_result"]["status"] == "llm_error"
    finally:
        st.cache_resource.clear()
