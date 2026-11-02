"""One reusable, pinned MiniLM encoder; no implicit model loading by Chroma."""
from dataclasses import asdict, dataclass
from typing import Protocol

import numpy as np

from .chunking import MODEL_NAME
from .cli import TOKENIZER_REVISION


@dataclass(frozen=True)
class EmbeddingSpec:
    model_name: str = MODEL_NAME
    model_revision: str = TOKENIZER_REVISION
    embedding_dimension: int = 384
    normalized: bool = True
    encoder: str = "sentence-transformers-5.1.2/encode-float32"
    max_sequence_length: int = 256

    def metadata(self) -> dict:
        return asdict(self)


class Encoder(Protocol):
    spec: EmbeddingSpec

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray: ...


def validate_vectors(vectors, count: int, dimension: int = 384) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.shape != (count, dimension):
        raise ValueError(f"Expected embeddings shape {(count, dimension)}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("Embeddings contain non-finite values")
    if not np.allclose(np.linalg.norm(array, axis=1), 1.0, atol=1e-5):
        raise ValueError("Embeddings must be nonzero and L2 normalized")
    return array


class MiniLMEncoder:
    spec = EmbeddingSpec()

    def __init__(self, cache_dir: str | None = None, offline: bool = True):
        from sentence_transformers import SentenceTransformer

        try:
            self.model = SentenceTransformer(
                self.spec.model_name, revision=self.spec.model_revision,
                cache_folder=cache_dir, local_files_only=offline, device="cpu",
                trust_remote_code=False,
            )
        except (OSError, ValueError, RuntimeError) as error:
            mode = "offline cache" if offline else "model download/cache"
            raise RuntimeError(
                f"MiniLM unavailable in {mode}. Cache the full pinned model using "
                "`rag-store --prepare-model --allow-download --cache-dir <directory>`, "
                "then reuse that directory offline. " + str(error)
            ) from error
        if self.model.get_sentence_embedding_dimension() != self.spec.embedding_dimension:
            raise ValueError("Loaded MiniLM has an incompatible embedding dimension")
        if self.model.max_seq_length != self.spec.max_sequence_length:
            raise ValueError("Loaded MiniLM has an incompatible maximum sequence length")

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not texts:
            return np.empty((0, self.spec.embedding_dimension), dtype=np.float32)
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input texts must be nonempty strings")
        # SentenceTransformer would otherwise silently truncate long query/input text.
        lengths = self.model.tokenizer(
            texts, add_special_tokens=True, truncation=False, return_length=True,
            verbose=False,
        )["length"]
        if any(length > self.spec.max_sequence_length for length in lengths):
            raise ValueError("Embedding input exceeds MiniLM's 256-token limit; re-chunk it")
        vectors = self.model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False, precision="float32",
        )
        return validate_vectors(vectors, len(texts), self.spec.embedding_dimension)
