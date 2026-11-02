"""Persistent Chroma ingestion and a configuration-checked handoff to Member B."""
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError

from .embeddings import EmbeddingSpec, Encoder, validate_vectors
from .jsonl import load_chunks

COLLECTIONS = {
    "fixed_150": "finance_fixed_150",
    "fixed_220_overlap_30": "finance_overlap_220",
}


def persistent_client(directory: Path):
    return chromadb.PersistentClient(
        path=str(directory), settings=Settings(anonymized_telemetry=False),
    )


def collection_metadata(strategy: str, spec: EmbeddingSpec) -> dict:
    if spec.embedding_dimension != 384 or spec.normalized is not True:
        raise ValueError("Phase 2 requires 384-dimensional normalized embeddings")
    return {**spec.metadata(), "schema_version": 1, "chunk_strategy": strategy,
            "distance_metric": "cosine"}


def check_collection(collection, strategy: str, spec: EmbeddingSpec) -> None:
    expected = collection_metadata(strategy, spec)
    actual = collection.metadata or {}
    mismatched = [key for key, value in expected.items() if actual.get(key) != value]
    configuration = collection.configuration
    if (configuration.get("hnsw") or {}).get("space") != "cosine":
        mismatched.append("actual HNSW distance metric")
    # Check actual persisted vectors as well as the declared dimension.
    sample = collection.get(limit=1, include=["embeddings"])["embeddings"]
    if sample is not None and len(sample):
        validate_vectors(sample, 1, spec.embedding_dimension)
    if mismatched:
        raise ValueError(
            f"Incompatible collection {collection.name}: {', '.join(mismatched)}. "
            "Use the original encoder/configuration or explicitly --rebuild this collection."
        )


def open_collection(directory: Path, strategy: str, spec: EmbeddingSpec = EmbeddingSpec()):
    """Get an existing checked collection, without creating or changing it.

    Call query(query_embeddings=...) with the same encoder. No default embedding
    function is attached, so query_texts cannot silently select another model.
    """
    if strategy not in COLLECTIONS:
        raise ValueError(f"Unknown chunk strategy: {strategy}")
    collection = persistent_client(directory).get_collection(
        COLLECTIONS[strategy], embedding_function=None,
    )
    check_collection(collection, strategy, spec)
    return collection


def storage_size(directory: Path) -> int:
    """Logical file sizes, including SQLite, its journal, and all index files."""
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def ingest_jsonl(paths: list[Path], directory: Path, encoder: Encoder,
                 batch_size: int = 32, rebuild: bool = False) -> dict:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    grouped = load_chunks(paths)
    for strategy in grouped:
        collection_metadata(strategy, encoder.spec)
    client = persistent_client(directory)
    batch_size = min(batch_size, client.get_max_batch_size())
    existing = {}
    # Preflight every targeted collection before the first mutation.
    for strategy in sorted(grouped):
        try:
            collection = client.get_collection(COLLECTIONS[strategy], embedding_function=None)
        except NotFoundError:
            continue
        if not rebuild:
            check_collection(collection, strategy, encoder.spec)
        existing[strategy] = collection

    report = {"processed_chunks": 0, "embedding_seconds": 0.0,
              "insertion_seconds": 0.0, "effective_batch_size": batch_size,
              "collections": {}}
    for strategy in sorted(grouped):
        collection = existing.get(strategy)
        if rebuild and collection is not None:
            client.delete_collection(COLLECTIONS[strategy])
            collection = None
        if collection is None:
            collection = client.create_collection(
                COLLECTIONS[strategy], embedding_function=None,
                metadata=collection_metadata(strategy, encoder.spec),
                configuration={"hnsw": {"space": "cosine"}},
            )
        chunks = grouped[strategy]
        before = collection.count()
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset:offset + batch_size]
            started = perf_counter()
            vectors = validate_vectors(
                encoder.encode([c.text for c in batch], batch_size), len(batch),
                encoder.spec.embedding_dimension,
            )
            report["embedding_seconds"] += perf_counter() - started
            metadata = []
            for chunk in batch:
                row = asdict(chunk)
                del row["text"]
                del row["chunk_id"]
                metadata.append(row)
            started = perf_counter()
            collection.upsert(
                ids=[c.chunk_id for c in batch], documents=[c.text for c in batch],
                embeddings=vectors.tolist(), metadatas=metadata,
            )
            report["insertion_seconds"] += perf_counter() - started
            report["processed_chunks"] += len(batch)
        report["collections"][collection.name] = {
            "processed_chunks": len(chunks), "records_before": before,
            "records_after": collection.count(),
        }
    report["storage_bytes"] = storage_size(directory)
    return report
