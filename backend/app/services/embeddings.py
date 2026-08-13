"""Embedding providers (LIB-IDX-05).

Runs locally via fastembed. The Implementation Plan names Google
text-embedding-004, but the AgentRouter key serves only chat models — its
/v1/embeddings route returns "no available channel" for every embedding model.
Local ONNX inference removes that dependency.

To switch to a hosted provider: add a subclass, register it in get_provider(),
and add an Alembic migration changing the vector column dimension. The
dimension in the DB and the provider's must always agree.
"""
import logging
import threading
from abc import ABC, abstractmethod

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    dimension: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages for storage."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""


class FastEmbedProvider(EmbeddingProvider):
    """BAAI/bge-small-en-v1.5 — 384-dim, ONNX, CPU-only.

    The model is loaded lazily and cached per process: Celery forks workers, and
    eager loading at import time would pay the cost in every process including
    the API, which never embeds anything.
    """

    def __init__(self, model_name: str | None = None, dimension: int | None = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.dimension = dimension or settings.EMBEDDING_DIM
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

        # A dimension mismatch here would be silently truncated or rejected by
        # pgvector at insert time, so fail with a message that names the fix.
        if vectors and len(vectors[0]) != self.dimension:
            raise ValueError(
                f"Model {self.model_name} returned {len(vectors[0])}-dim vectors but "
                f"EMBEDDING_DIM is {self.dimension}. Update EMBEDDING_DIM and migrate "
                f"the document_chunks.embedding column to match."
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        # bge models expect a retrieval instruction prefix on queries but not on
        # passages; query_embed applies it.
        return next(iter(model.query_embed([text]))).tolist()


_provider: EmbeddingProvider | None = None
_provider_lock = threading.Lock()


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                name = settings.EMBEDDING_PROVIDER.lower()
                if name == "fastembed":
                    _provider = FastEmbedProvider()
                else:
                    raise ValueError(
                        f"Unknown EMBEDDING_PROVIDER '{settings.EMBEDDING_PROVIDER}'. "
                        f"Supported: fastembed"
                    )
    return _provider


def set_provider(provider: EmbeddingProvider | None) -> None:
    """Override the provider — used by tests to avoid loading the real model."""
    global _provider
    _provider = provider
