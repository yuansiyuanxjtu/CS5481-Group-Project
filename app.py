"""Run from the repository root: .venv/bin/python -m streamlit run app.py"""
import os

import streamlit as st

from rag_app.config import Settings
from rag_app.demo import create_demo_service

st.set_page_config(page_title="Evidence QA | CS5481", page_icon="📚", layout="centered")
st.title("Knowledge Base Q&A")
st.caption("CS5481 · Answers grounded in five official financial AI publications")
st.write("Ask a question in English. Check each cited passage and its physical PDF page.")


@st.cache_resource
def service(profile):
    return create_demo_service(Settings.from_env(), profile)


with st.form("question_form"):
    question = st.text_area("Your question", max_chars=2000, height=100,
                            placeholder="Which earlier HKMA document did the October 2026 guidance supersede?")
    submitted = st.form_submit_button("Submit", type="primary")

if submitted:
    st.session_state.pop("qa_result", None)
    if not question.strip():
        st.warning("Enter a question first.")
    else:
        with st.spinner("Retrieving evidence and checking the answer…"):
            try:
                cfg = Settings.from_env()
                profile = os.environ.get("RAG_DEMO_PROFILE", "baseline").strip()
                from rag_app.demo_budget import enforce_profile
                enforce_profile(profile)  # also guard already-cached baseline services
                key_present = bool(os.environ.get('OFOX_API_KEY','').strip()) if profile == 'ofox_joint_pairs8' else bool(cfg.api_key)
                if not key_present:
                    key_name = 'OFOX_API_KEY' if profile == 'ofox_joint_pairs8' else 'LLM_API_KEY'
                    st.error(f"LLM is not configured. Add {key_name} to the local .env file and restart the app.")
                else:
                    st.session_state["qa_result"] = service(profile).answer_question(question)
                    st.session_state["qa_question"] = question
            except Exception:
                st.error("Application setup is incomplete. Check .env and reproduce the experiment data using README.")

result = st.session_state.get("qa_result")
if result:
    st.subheader("Answer")
    st.caption(st.session_state["qa_question"])
    if result["status"] == "answered":
        st.text(result["answer"])
    elif result["status"] == "insufficient_evidence":
        st.info(result["answer"])
    else:
        st.error(result["error"] or "The service could not produce a verified answer.")
    if result["citations"]:
        st.subheader("Sources")
        for citation in result["citations"]:
            st.write(f'[{citation["evidence_id"]}] {citation["title"]}')
            st.caption(f'Published {citation["publication_date"]} · Physical PDF page {citation["page_number"]} · Status: {citation["regulatory_status"]}')
            st.link_button("Open official PDF", citation["page_url"])
            st.text(citation["source_url"])
            st.caption(f'Document: {citation["document_id"]} · Chunk: {citation["chunk_id"]}')
            for quote in citation["excerpts"]:
                st.text(quote)
            if citation["regulatory_status"] == "superseded":
                st.warning("Historical source: this publication is marked superseded.")
            elif citation["regulatory_status"] == "unknown":
                st.caption("Unknown status does not establish that a publication is currently applicable.")
    with st.expander("Retrieved evidence"):
        for hit in result["retrieved"]:
            st.write(f'[{hit["evidence_id"]}] {hit["title"]} · Physical page {hit["page_number"]}')
            st.caption(f'Cosine distance: {hit["distance"]:.4f} (smaller means closer; not a probability)')
            st.text(hit["text"])
    st.caption(f'Status: {result["status"]} · Elapsed: {result["elapsed_seconds"]:.2f}s')
    st.download_button("Download this QA record", data=__import__("json").dumps(
        {"question": st.session_state["qa_question"], **result}, ensure_ascii=False, indent=2),
        file_name="qa_record.json", mime="application/json")
