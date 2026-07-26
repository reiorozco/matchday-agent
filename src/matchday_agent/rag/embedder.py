"""Text embedding via fastembed (local ONNX, no API keys, no rate limits).

Decision locked in docs/decisions.md § 2.x: intfloat/multilingual-e5-large
(1024-dim, MIT, ~100 languages, 512-token truncation). fastembed's
passage_embed / query_embed helpers auto-prepend the E5-required
"passage: " / "query: " prefixes; we never inject them by hand.

The `TextEmbedding` instance is a process-wide singleton because the
model file is 2.24 GB and loading it into ORT is expensive (~3-5 s).
"""

from __future__ import annotations

from threading import Lock

from fastembed import TextEmbedding

_MODEL_NAME = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024

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
