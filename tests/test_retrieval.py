import json
from unittest.mock import Mock

import numpy as np
import pytest

import rag_retrieval
from scripts.eval_retrieval import evidence_ranks


@pytest.fixture
def backend(tmp_path, monkeypatch):
    context = {"dataset_version": "synthetic_test"}
    for arm in rag_retrieval.ARMS:
        folder = tmp_path / arm
        (folder / "chroma").mkdir(parents=True)
        (folder / "chroma/chroma.sqlite3").touch()
        (folder / "collection_context.json").write_text(json.dumps(context), encoding="utf-8")
    encoder = Mock()
    encoder.encode.return_value = np.array([[1.0, 0.0]])
    create_encoder = Mock(return_value=encoder)
    store = Mock()
    store.count.return_value = 2
    metadata = {
        "source_url": "https://example.invalid/policy.pdf", "page_number": 3,
        "title": "Test policy", "publication_date": "2000-01-01",
    }
    store.query.return_value = {
        "ids": [["first", "second"]], "documents": [["Historical text", "Other text"]],
        "distances": [[0.7, 0.2]],
        "metadatas": [[
            {**metadata, "document_id": "older", "regulatory_status": "superseded"},
            {**metadata, "document_id": "newer", "regulatory_status": "unknown"},
        ]],
    }
    open_store = Mock(return_value=store)
    monkeypatch.setattr(rag_retrieval, "MiniLMEncoder", create_encoder)
    monkeypatch.setattr(rag_retrieval, "open_collection", open_store)
    retriever = rag_retrieval.Retriever(tmp_path, tmp_path / "cache")
    return retriever, encoder, create_encoder, store, open_store, context


def test_retrieve_sorted_with_physical_citations_and_temporal_status(backend, monkeypatch):
    retriever, encoder, create_encoder, store, open_store, context = backend
    monkeypatch.setattr(rag_retrieval, "_default", retriever)
    hits = rag_retrieval.retrieve("  Example question?  ")
    assert hits == [
        {"chunk_id": "second", "document_id": "newer", "text": "Other text", "distance": 0.2,
         "source_url": "https://example.invalid/policy.pdf", "page_number": 3,
         "title": "Test policy", "publication_date": "2000-01-01", "regulatory_status": "unknown"},
        {"chunk_id": "first", "document_id": "older", "text": "Historical text", "distance": 0.7,
         "source_url": "https://example.invalid/policy.pdf", "page_number": 3,
         "title": "Test policy", "publication_date": "2000-01-01", "regulatory_status": "superseded"},
    ]
    create_encoder.assert_called_once_with(str(retriever.cache_dir), offline=True)
    encoder.encode.assert_called_once_with(["Example question?"], batch_size=1)
    store.query.assert_called_once_with(query_embeddings=[[1.0, 0.0]], n_results=2,
                                        include=["documents", "metadatas", "distances"])
    open_store.assert_called_once_with(retriever.experiment_dir / "enhanced/chroma", "fixed_150",
                                       encoder.spec, context=context)


def test_reuse_encoder_and_keep_arms_separate(backend):
    retriever, encoder, create_encoder, _, open_store, context = backend
    retriever.retrieve("First?", collection="fixed_220", arm="baseline")
    retriever.retrieve("Second?", collection="fixed_220", arm="baseline")
    retriever.retrieve("Third?", collection="fixed_220", arm="enhanced")
    assert open_store.call_count == 2
    assert encoder.encode.call_count == 3
    open_store.assert_called_with(retriever.experiment_dir / "enhanced/chroma", "fixed_220",
                                  encoder.spec, context=context)
    create_encoder.assert_called_once()


@pytest.mark.parametrize("question,k,options", [
    ("  ", 5, {}), (None, 5, {}), ("Question?", 0, {}), ("Question?", True, {}),
    ("Question?", 2.5, {}), ("Question?", 5, {"arm": "unknown"}),
    ("Question?", 5, {"collection": "unknown"}),
])
def test_validate_inputs_before_opening_store(question, k, options, tmp_path):
    with pytest.raises(ValueError):
        rag_retrieval.Retriever(tmp_path).retrieve(question, k, **options)


def test_missing_database_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run the Phase 2.6 benchmark"):
        rag_retrieval.Retriever(tmp_path).retrieve("Question?")


def test_empty_collection_returns_no_hits(backend):
    retriever, encoder, _, store, _, _ = backend
    store.count.return_value = 0
    assert retriever.retrieve("Question?") == []
    encoder.encode.assert_not_called()
    store.query.assert_not_called()


def test_evidence_ranks_use_document_and_inclusive_physical_page_range():
    hits = [
        {"document_id": "b", "page_number": 3}, {"document_id": "a", "page_number": 2},
        {"document_id": "a", "page_number": 4}, {"document_id": "a", "page_number": 3},
    ]
    labels = [
        {"document_id": "a", "page_start": 3, "page_end": 4},
        {"document_id": "b", "page_start": 3, "page_end": 3},
        {"document_id": "b", "page_start": 2, "page_end": 2},
    ]
    assert evidence_ranks(hits, labels) == [3, 1, None]
