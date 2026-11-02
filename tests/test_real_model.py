"""Opt-in real MiniLM smoke test; synthetic PDFs, no network or corpus claims."""
import os
from pathlib import Path

import numpy as np
import pytest

from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.pipeline import run_pipeline
from rag_ingest.vector_store import ingest_jsonl, open_collection


@pytest.mark.skipif(os.environ.get("RAG_TEST_REAL_MODEL") != "1", reason="Set RAG_TEST_REAL_MODEL=1 after caching MiniLM weights")
def test_real_minilm_pdf_to_persistent_chroma(corpus, tokenizer, tmp_path):
    processed = tmp_path / "processed"
    run_pipeline(*corpus, processed, tokenizer)
    encoder = MiniLMEncoder(
        str(Path(__file__).resolve().parents[1] / ".cache/huggingface/hub"), offline=True,
    )
    db = tmp_path / "chroma"
    report = ingest_jsonl(sorted(processed.glob("*.jsonl")), db, encoder, batch_size=2)
    assert report["processed_chunks"] == 8
    for strategy in ("fixed_150", "fixed_220_overlap_30"):
        collection = open_collection(db, strategy, encoder.spec)
        assert collection.count() == 4
        stored = collection.get(include=["embeddings"])["embeddings"]
        assert stored.shape == (4, 384)
        assert np.allclose(np.linalg.norm(stored, axis=1), 1.0, atol=1e-5)
        query = encoder.encode(["Banking risk governance."], batch_size=1)
        result = collection.query(query_embeddings=query.tolist(), n_results=1,
                                  include=["metadatas", "distances"])
        assert result["ids"][0] == [f"doc001_p1_c1_{strategy}"]
        assert result["metadatas"][0][0]["source_url"] == "https://example.invalid/alpha.pdf"
        assert result["distances"][0][0] == pytest.approx(0, abs=1e-5)
