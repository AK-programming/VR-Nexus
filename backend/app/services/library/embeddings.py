"""
Section 6.1 - Document Indexing & Vectorization Pipeline
Linked requirement: LIB-IDX-05

Runs locally via fastembed (ONNX, CPU-only) rather than a hosted API.
This was a deliberate switch away from the Implementation Plan's original
choice of Google's text-embedding-004: the team decided against adding a
Google API key dependency, and separately, the third-party LLM router
some teammates were using for other calls doesn't serve embedding models
at all. Local inference removes both problems, at the cost of the vectors
being a different model than originally planned - anything embedded
before this switch would need re-indexing to be comparable.

To switch to a hosted provider later: add a subclass, register it in
get_provider(), and add an Alembic migration changing the vector column's
dimension if the new model's dimension differs. The dimension in the DB
and the provider's must always agree, or pgvector will reject inserts.
"""
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()


class EmbeddingProvider(ABC):
    dimension: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""


class FastEmbedProvider(EmbeddingProvider):
    """BAAI/bge-base-en-v1.5 by default - 768-dim, matching chunks.embedding's
    column so it's a drop-in replacement for whatever was configured before.

    The model is loaded lazily and cached per process: Celery forks
    workers, and eager loading at import time would pay the cost in every
    process including the API, which never embeds anything itself.
    """

    def __init__(self, model_name: Optional[str] = None, dimension: Optional[int] = None):
        self.model_name = model_name or _settings.EMBEDDING_MODEL
        self.dimension = dimension or _settings.EMBEDDING_DIM
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    logger.info("Loading embedding model %s", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name)
                    logger.info("Embedding model ready")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = [v.tolist() for v in model.embed(texts)]

        # A dimension mismatch would otherwise be silently rejected by
        # pgvector at insert time - fail here instead, with a message that
        # names the actual fix.
        if vectors and len(vectors[0]) != self.dimension:
            raise ValueError(
                f"Model {self.model_name} returned {len(vectors[0])}-dim vectors but "
                f"EMBEDDING_DIM is {self.dimension}. Update EMBEDDING_DIM and migrate "
                f"the chunks.embedding column to match."
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        # bge models expect a retrieval-instruction prefix on queries but
        # not on passages; query_embed applies it automatically.
        return next(iter(model.query_embed([text]))).tolist()


_provider: Optional[EmbeddingProvider] = None
_provider_lock = threading.Lock()


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                name = _settings.EMBEDDING_PROVIDER.lower()
                if name == "fastembed":
                    _provider = FastEmbedProvider()
                else:
                    raise ValueError(
                        f"Unknown EMBEDDING_PROVIDER '{_settings.EMBEDDING_PROVIDER}'. "
                        f"Supported: fastembed"
                    )
    return _provider


def set_provider(provider: Optional[EmbeddingProvider]) -> None:
    """Override the provider - used by tests to avoid loading the real model."""
    global _provider
    _provider = provider
