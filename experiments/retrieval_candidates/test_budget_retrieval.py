"""Check fixed budgets, original-chunk retention and explicit caller configuration."""
import numpy as np
import pytest

from boundary_retrieval import BoundaryRetriever
from budget_retrieval import BASELINE, BUDGET, MODES, BudgetRetriever


def synthetic_engine(monkeypatch):
    engine = BudgetRetriever.__new__(BudgetRetriever)
    base = [f"a{i}" for i in range(5)]
    vector = np.array([1.0, 0.0])
    monkeypatch.setattr(BoundaryRetriever, "candidates", lambda self, question, modes: ({BASELINE: base}, vector))
    engine.indexed_text = {key: "An unfinished statement" for key in base}
    engine.next_on_page = {"a0": "n0", "a1": "n1", "a2": "n2"}
    engine.next_reading_chunk = {**engine.next_on_page, "a3": "n3"}
    engine.routed_queries = lambda question: {"A": question}
    engine.ranked_passages = lambda doc, query, rerank: [({"chunk_id": f"s{i}"}, 1.0) for i in range(10)]
    class Store:
        def query(self, **kwargs):
            ids = [*base, *(f"d{i}" for i in range(10))]
            return {"ids": [ids], "distances": [[i/100 for i in range(len(ids))]]}
    engine.collection = Store()
    return engine, base


def test_every_expansion_preserves_all_five_original_chunks(monkeypatch):
    engine, base = synthetic_engine(monkeypatch)
    choices, _ = engine.expansion_choices("Question", MODES)
    assert all(ids[:5] == base for ids in choices.values())
    assert all(len(ids) == BUDGET[mode] and len(set(ids)) == len(ids) for mode, ids in choices.items())


def test_top5_and_top8_callers_must_use_the_corresponding_mode():
    engine = BudgetRetriever(mode="source_neighbor8")
    with pytest.raises(ValueError, match="Top-K"):
        engine.retrieve("Question", top_k=5)


def test_candidate_does_not_modify_chunk_text(monkeypatch):
    engine, _ = synthetic_engine(monkeypatch)
    original = dict(engine.indexed_text)
    engine.expansion_choices("Question", ["source_neighbor8"])
    assert engine.indexed_text == original
