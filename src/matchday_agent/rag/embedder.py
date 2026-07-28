"""Text embedding via fastembed (local ONNX, no API keys, no rate limits).

Model swap per decisions.md § 8.10 (audit response): the original
intfloat/multilingual-e5-large (2.24 GB, 1024-dim) OOM-killed the
512 MB Fly VM on first RAG call. fastembed's catalog does not include
E5's smaller variants, so downgraded to
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (~220 MB,
384-dim, ~50 languages including EN+ES, Apache-2.0, 512-token
truncation) — the smallest multilingual embedder fastembed supports.
Fits comfortably in the 1 GB VM (bumped per § 8.10 too).

fastembed's passage_embed / query_embed helpers stay the same across
models — for MiniLM they're aliases for the generic embed() call
(no E5-style "passage: " / "query: " prefix needed).

The `TextEmbedding` instance is a process-wide singleton — the smaller
model loads in ~1-2 s. Pre-baked into the Docker image via a
Dockerfile RUN step so cold starts don't re-download the ~220 MB
weights.
"""

from __future__ import annotations

from threading import Lock

from fastembed import TextEmbedding

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

_model: TextEmbedding | None = None
_model_lock = Lock()


def get_embedder() -> TextEmbedding:
    """Return the process-wide TextEmbedding singleton, loading it on first call."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = TextEmbedding(model_name=_MODEL_NAME)
    return _model


def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed a batch of document/passage chunks for storage in pgvector.

    fastembed injects the E5 "passage: " prefix internally via passage_embed.
    """
    model = get_embedder()
    vectors = list(model.passage_embed(texts, batch_size=batch_size))
    return [v.tolist() for v in vectors]


def embed_query(query: str) -> list[float]:
    """Embed a single user query for similarity search against passages.

    fastembed injects the E5 "query: " prefix internally via query_embed.
    """
    model = get_embedder()
    vectors = list(model.query_embed([query]))
    return vectors[0].tolist()
