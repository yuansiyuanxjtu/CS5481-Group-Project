"""Page-preserving semantic retrieval for the Phase 2.6 collections."""

from functools import cached_property
import json
from pathlib import Path
from typing import TypedDict

from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.vector_store import ALL_COLLECTIONS, open_collection

DEFAULT_EXPERIMENT = Path("data/experiments/phase26_reproduction")
DEFAULT_CACHE = Path(".cache/huggingface/hub")
ARMS = ("baseline", "enhanced")


class RetrievalHit(TypedDict):
    chunk_id: str
    document_id: str
    text: str
    source_url: str
    page_number: int
    distance: float
    title: str
    publication_date: str
    regulatory_status: str


class Retriever:
    """Reuse one offline encoder and the checked collections for a completed run."""

    def __init__(self, experiment_dir: Path = DEFAULT_EXPERIMENT, cache_dir: Path = DEFAULT_CACHE):
        self.experiment_dir = Path(experiment_dir)
        self.cache_dir = Path(cache_dir)
        self._collections = {}

    @cached_property
    def _encoder(self) -> MiniLMEncoder:
        return MiniLMEncoder(str(self.cache_dir), offline=True)

    def _open(self, arm: str, collection: str):
        key = (arm, collection)
        if key not in self._collections:
            folder = self.experiment_dir / arm
            database = folder / "chroma"
            if not (database / "chroma.sqlite3").is_file():
                raise FileNotFoundError(f"Missing experiment database: {database}. Run the Phase 2.6 benchmark first.")
            context = json.loads((folder / "collection_context.json").read_text(encoding="utf-8"))
            self._collections[key] = open_collection(database, collection, self._encoder.spec, context=context)
        return self._collections[key]

    def retrieve(self, question: str, top_k: int = 5, *, collection: str = "fixed_150",
                 arm: str = "enhanced") -> list[RetrievalHit]:
        """Return up to top_k chunks in ascending cosine-distance order."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string")
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        if arm not in ARMS:
            raise ValueError(f"Unknown cleaning arm: {arm!r}")
        if not isinstance(collection, str) or collection not in ALL_COLLECTIONS:
            raise ValueError(f"Unknown chunk strategy: {collection!r}")

        store = self._open(arm, collection)
        limit = min(top_k, store.count())
        if not limit:
            return []
        vector = self._encoder.encode([question.strip()], batch_size=1)
        result = store.query(query_embeddings=vector.tolist(), n_results=limit,
                             include=["documents", "metadatas", "distances"])
        hits: list[RetrievalHit] = []
        for chunk_id, text, metadata, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True,
        ):
            hits.append({
                "chunk_id": chunk_id,
                "document_id": metadata["document_id"],
                "text": text,
                "source_url": metadata["source_url"],
                "page_number": metadata["page_number"],
                "distance": float(distance),
                "title": metadata["title"],
                "publication_date": metadata["publication_date"],
                "regulatory_status": metadata["regulatory_status"],
            })
        return sorted(hits, key=lambda hit: (hit["distance"], hit["chunk_id"]))


_default = Retriever()


def retrieve(question: str, top_k: int = 5, *, collection: str = "fixed_150",
             arm: str = "enhanced") -> list[RetrievalHit]:
    """Query the default reproduction run from the repository root."""
    return _default.retrieve(question, top_k, collection=collection, arm=arm)
