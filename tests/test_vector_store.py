"""Synthetic input and mock encodings; persistence/query tests use real Chroma."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from rag_ingest.embeddings import EmbeddingSpec, MiniLMEncoder, validate_vectors
from rag_ingest.jsonl import load_chunks
from rag_ingest.models import Chunk
from rag_ingest.vector_store import (
    COLLECTIONS, collection_metadata, ingest_jsonl, open_collection, persistent_client,
)


class FakeEncoder:
    # These vectors are explicitly labeled synthetic and cannot mix with MiniLM.
    spec = EmbeddingSpec(model_name="test/synthetic-hash", model_revision="fixture-v1", encoder="test-only")

    def __init__(self):
        self.calls = []

    def encode(self, texts, batch_size):
        self.calls.append((len(texts), batch_size))
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        for i, text in enumerate(texts):
            index = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big") % 384
            vectors[i, index] = 1.0
        return vectors


def chunk(index=1, strategy="fixed_150", text=None):
    return Chunk(f"doc001_p3_c{index}_{strategy}", "doc001", "fixture.pdf",
                 "https://example.invalid/fixture.pdf", 3,
                 text or f"Synthetic fixture {index}", strategy, 4)


def write_chunks(path, rows):
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path):
    return [
        write_chunks(tmp_path / "fixed.jsonl", [chunk(i) for i in range(1, 4)]),
        write_chunks(tmp_path / "overlap.jsonl", [chunk(i, "fixed_220_overlap_30") for i in range(1, 3)]),
    ]


def test_dimensions_normalization_and_bad_vectors():
    vectors = FakeEncoder().encode(["test", "text"], 2)
    assert validate_vectors(vectors, 2).shape == (2, 384)
    for invalid in (np.ones((1, 383)), np.zeros((1, 384)), np.ones((1, 384)),
                    np.full((1, 384), np.nan), np.full((1, 384), np.inf)):
        with pytest.raises(ValueError):
            validate_vectors(invalid, 1)


def test_persistence_metadata_isolation_repeat_and_smoke(inputs, tmp_path):
    encoder = FakeEncoder()
    db = tmp_path / "chroma"
    report = ingest_jsonl(inputs, db, encoder, batch_size=2)
    assert encoder.calls == [(2, 2), (1, 2), (2, 2)]
    assert report["processed_chunks"] == 5
    assert report["embedding_seconds"] >= 0
    assert report["insertion_seconds"] >= 0
    assert report["storage_bytes"] > 0
    assert report["collections"]["finance_fixed_150"]["records_after"] == 3
    assert report["collections"]["finance_overlap_220"]["records_after"] == 2
    for strategy, expected in (("fixed_150", 3), ("fixed_220_overlap_30", 2)):
        collection = open_collection(db, strategy, encoder.spec)
        assert collection.count() == expected
        assert collection.configuration["hnsw"]["space"] == "cosine"
        row = collection.get(ids=[chunk(1, strategy).chunk_id], include=["metadatas", "documents", "embeddings"])
        metadata = asdict(chunk(1, strategy))
        del metadata["text"]
        del metadata["chunk_id"]
        assert row["metadatas"] == [metadata]
        assert row["documents"] == [chunk(1, strategy).text]
        assert row["embeddings"].shape == (1, 384)
        result = collection.query(
            query_embeddings=encoder.encode([chunk(1, strategy).text], 1).tolist(),
            n_results=1, include=["metadatas", "documents", "distances"],
        )
        assert result["ids"] == [[chunk(1, strategy).chunk_id]]
        assert result["distances"][0][0] == pytest.approx(0, abs=1e-6)
        assert result["metadatas"][0][0]["page_number"] == 3
    second = ingest_jsonl(inputs, db, encoder, batch_size=2)
    assert second["collections"]["finance_fixed_150"]["records_before"] == 3
    assert second["collections"]["finance_fixed_150"]["records_after"] == 3
    assert second["collections"]["finance_overlap_220"]["records_after"] == 2


def test_persistence_across_process(inputs, tmp_path):
    import os
    import subprocess
    import sys

    db = tmp_path / "chroma"
    ingest_jsonl(inputs, db, FakeEncoder())
    script = """
import sys
from pathlib import Path
from rag_ingest.vector_store import persistent_client
client = persistent_client(Path(sys.argv[1]))
a = client.get_collection('finance_fixed_150', embedding_function=None)
b = client.get_collection('finance_overlap_220', embedding_function=None)
assert a.count() == 3 and b.count() == 2
assert a.get(limit=1)['metadatas'][0]['page_number'] == 3
print('persisted')
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", script, str(db)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "persisted" in result.stdout


@pytest.mark.parametrize("change", [
    {"model_name": "other-model"}, {"model_revision": "other-revision"},
    {"normalized": False}, {"embedding_dimension": 768},
    {"encoder": "other-encoder"}, {"chunk_strategy": "other-strategy"},
    {"schema_version": 99}, {"max_sequence_length": 512},
])
def test_configuration_mismatch_rejected(inputs, tmp_path, change):
    db = tmp_path / "chroma"
    encoder = FakeEncoder()
    ingest_jsonl(inputs, db, encoder)
    collection = persistent_client(db).get_collection(COLLECTIONS["fixed_150"], embedding_function=None)
    collection.modify(metadata={**collection.metadata, **change})
    with pytest.raises(ValueError, match="Incompatible collection"):
        ingest_jsonl(inputs, db, encoder)
    assert collection.count() == 3
    assert open_collection(db, "fixed_220_overlap_30", encoder.spec).count() == 2


def test_actual_distance_and_dimension_checked(inputs, tmp_path):
    for label, config, vectors in [
        ("wrong-distance", {"hnsw": {"space": "l2"}}, [[1.0] + [0.0] * 383]),
        ("wrong-dimension", {"hnsw": {"space": "cosine"}}, [[1.0, 0.0]]),
    ]:
        db = tmp_path / label
        encoder = FakeEncoder()
        client = persistent_client(db)
        collection = client.create_collection(
            COLLECTIONS["fixed_150"], embedding_function=None,
            metadata=collection_metadata("fixed_150", encoder.spec), configuration=config,
        )
        collection.add(ids=["existing"], documents=["fixture"], embeddings=vectors)
        with pytest.raises(ValueError):
            ingest_jsonl(inputs, db, encoder)
        assert collection.count() == 1
        assert len(client.list_collections()) == 1  # No second collection created.


def test_foreign_collection_rejected_and_explicit_rebuild(inputs, tmp_path):
    db = tmp_path / "chroma"
    encoder = FakeEncoder()
    client = persistent_client(db)
    client.create_collection(COLLECTIONS["fixed_150"], embedding_function=None)
    client.create_collection("unrelated_collection", embedding_function=None)
    with pytest.raises(ValueError, match="Incompatible collection"):
        ingest_jsonl(inputs, db, encoder)
    ingest_jsonl(inputs, db, encoder, rebuild=True)
    assert open_collection(db, "fixed_150", encoder.spec).count() == 3
    assert client.get_collection("unrelated_collection", embedding_function=None).count() == 0
    # Upsert changes records but does not remove stale IDs; rebuild replaces only targets.
    one_row = write_chunks(inputs[0], [chunk(1, text="Updated fixture")])
    ingest_jsonl([one_row], db, encoder)
    assert open_collection(db, "fixed_150", encoder.spec).count() == 3
    assert open_collection(db, "fixed_150", encoder.spec).get(ids=[chunk().chunk_id])["documents"] == ["Updated fixture"]
    ingest_jsonl([one_row], db, encoder, rebuild=True)
    assert open_collection(db, "fixed_150", encoder.spec).count() == 1
    assert open_collection(db, "fixed_220_overlap_30", encoder.spec).count() == 2


@pytest.mark.parametrize("body", [
    "", "\n", "{bad json}\n", "[]\n", "{}\n",
    json.dumps({**asdict(chunk()), "text": ""}) + "\n",
    json.dumps({**asdict(chunk()), "page_number": True}) + "\n",
    json.dumps({**asdict(chunk()), "page_number": 0}) + "\n",
    json.dumps({**asdict(chunk()), "token_count": 151}) + "\n",
    json.dumps({**asdict(chunk()), "token_count": "4"}) + "\n",
    json.dumps({**asdict(chunk()), "chunk_strategy": "unknown"}) + "\n",
    json.dumps({**asdict(chunk()), "source_url": "missing"}) + "\n",
    json.dumps({**asdict(chunk()), "chunk_id": "mismatch"}) + "\n",
    json.dumps({**asdict(chunk()), "extra": "field"}) + "\n",
    json.dumps(asdict(chunk())) + "\n" + json.dumps(asdict(chunk())) + "\n",
])
def test_empty_and_malformed_fail_before_database_changes(tmp_path, body):
    path = tmp_path / "bad.jsonl"
    path.write_text(body)
    db = tmp_path / "chroma"
    encoder = FakeEncoder()
    with pytest.raises(ValueError):
        ingest_jsonl([path], db, encoder, rebuild=True)
    assert not db.exists()
    assert not encoder.calls


def test_missing_and_duplicate_input(inputs, tmp_path):
    with pytest.raises(ValueError):
        load_chunks([])
    with pytest.raises(FileNotFoundError):
        load_chunks([tmp_path / "missing.jsonl"])
    with pytest.raises(ValueError, match="Duplicate chunk_id"):
        load_chunks([inputs[0], inputs[0]])
    with pytest.raises(ValueError, match="batch_size"):
        ingest_jsonl(inputs, tmp_path / "chroma", FakeEncoder(), batch_size=0)


def test_incompatible_encoder_rejected(inputs, tmp_path):
    encoder = FakeEncoder()
    encoder.spec = replace(encoder.spec, normalized=False)
    with pytest.raises(ValueError, match="384-dimensional normalized"):
        ingest_jsonl(inputs, tmp_path / "chroma", encoder)
    encoder.spec = FakeEncoder.spec
    encoder.encode = lambda texts, batch_size: np.zeros((len(texts), 384))
    with pytest.raises(ValueError, match="normalized"):
        ingest_jsonl(inputs, tmp_path / "chroma", encoder)
    assert persistent_client(tmp_path / "chroma").get_collection("finance_fixed_150").count() == 0


def test_model_loaded_once_normalized_batches_and_no_truncation(monkeypatch):
    import sentence_transformers

    fixture = FakeEncoder()
    model = SimpleNamespace(
        max_seq_length=256,
        get_sentence_embedding_dimension=lambda: 384,
        tokenizer=Mock(return_value={"length": [6, 6]}),
        encode=Mock(side_effect=lambda texts, **kw: fixture.encode(texts, kw["batch_size"])),
    )
    constructor = Mock(return_value=model)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", constructor)
    encoder = MiniLMEncoder("test-cache", offline=True)
    assert encoder.encode(["fixture one", "fixture two"], 2).shape == (2, 384)
    encoder.encode(["fixture three", "fixture four"], 2)
    constructor.assert_called_once()
    assert constructor.call_args.kwargs["local_files_only"] is True
    assert constructor.call_args.kwargs["revision"] == EmbeddingSpec().model_revision
    assert model.encode.call_count == 2
    assert model.encode.call_args.kwargs["normalize_embeddings"] is True
    assert model.encode.call_args.kwargs["precision"] == "float32"
    model.tokenizer.return_value = {"length": [257]}
    with pytest.raises(ValueError, match="256-token"):
        encoder.encode(["too long"], 1)
    assert model.encode.call_count == 2
    assert encoder.encode([], 1).shape == (0, 384)


def test_missing_model_error(monkeypatch):
    import sentence_transformers

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", Mock(side_effect=OSError("No weights cached")))
    with pytest.raises(RuntimeError, match="prepare-model.*allow-download"):
        MiniLMEncoder("empty-cache", offline=True)


def test_store_cli_validation_and_report(monkeypatch, inputs, tmp_path, capsys):
    from rag_ingest import store_cli

    constructor = Mock(return_value=FakeEncoder())
    monkeypatch.setattr(store_cli, "MiniLMEncoder", constructor)
    monkeypatch.setattr("sys.argv", ["rag-store", "--input", *map(str, inputs), "--db-dir", str(tmp_path / "chroma"), "--batch-size", "2"])
    store_cli.main()
    report = json.loads(capsys.readouterr().out)
    assert report["processed_chunks"] == 5
    assert report["model_load_seconds"] >= 0
    constructor.assert_called_once_with(None, offline=True)
    constructor.reset_mock()
    empty = tmp_path / "empty.jsonl"
    empty.touch()
    monkeypatch.setattr("sys.argv", ["rag-store", "--input", str(empty)])
    with pytest.raises(SystemExit) as error:
        store_cli.main()
    assert error.value.code == 1
    assert "empty JSONL" in capsys.readouterr().err
    constructor.assert_not_called()
