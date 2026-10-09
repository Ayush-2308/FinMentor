"""Create embedding vectors with the configured provider.

The database column is vector(1536). OpenAI text-embedding-3-small already
returns that size. Gemini gemini-embedding-001 is asked for 1536 dimensions
and then L2-normalized, because truncated Gemini vectors are not unit length.
"""

from __future__ import annotations

import logging
import math
import warnings
from typing import Optional

# requirements.txt pins this package. It is deprecated upstream, and importing
# it prints a FutureWarning. stacklevel points at this file, so a module filter
# on google.generativeai does not catch it.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai
from openai import OpenAI

from config import gemini_configure_lock, settings

logger = logging.getLogger(__name__)

_openai_client: Optional[OpenAI] = None
OPENAI_BATCH_SIZE = 64
GEMINI_BATCH_SIZE = 16


def embed_texts(texts: list[str], *, task: str) -> list[list[float]]:
    """Embed each string. `task` is `document` while indexing and `query` while searching."""
    if not texts:
        return []
    if task not in {"document", "query"}:
        raise ValueError("task must be 'document' or 'query'.")

    if settings.EMBEDDING_PROVIDER == "openai":
        vectors = _embed_openai(texts)
    else:
        vectors = _embed_gemini(texts, task=task)

    if len(vectors) != len(texts):
        raise RuntimeError("The embedding provider returned a different number of vectors than inputs.")
    for vector in vectors:
        if len(vector) != settings.EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"{settings.EMBEDDING_MODEL} returned {len(vector)} dimensions, "
                f"expected {settings.EMBEDDING_DIMENSIONS}."
            )
    return vectors


def _embed_openai(texts: list[str]) -> list[list[float]]:
    client = _get_openai_client()
    ordered: list[Optional[list[float]]] = [None] * len(texts)
    for start in range(0, len(texts), OPENAI_BATCH_SIZE):
        batch = texts[start : start + OPENAI_BATCH_SIZE]
        response = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        for item in response.data:
            ordered[start + item.index] = list(item.embedding)
    if any(vector is None for vector in ordered):
        raise RuntimeError("OpenAI omitted an embedding for one of the inputs.")
    return [vector for vector in ordered if vector is not None]


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=settings.EMBEDDING_API_KEY)
    return _openai_client


def _embed_gemini(texts: list[str], *, task: str) -> list[list[float]]:
    task_type = "retrieval_document" if task == "document" else "retrieval_query"
    vectors: list[list[float]] = []
    for start in range(0, len(texts), GEMINI_BATCH_SIZE):
        batch = texts[start : start + GEMINI_BATCH_SIZE]
        vectors.extend(_embed_gemini_batch(batch, task_type))
    return [_l2_normalize(vector) for vector in vectors]


def _embed_gemini_batch(texts: list[str], task_type: str) -> list[list[float]]:
    content: str | list[str] = texts[0] if len(texts) == 1 else texts
    with gemini_configure_lock:
        genai.configure(api_key=settings.EMBEDDING_API_KEY)
        try:
            result = genai.embed_content(
                model=settings.EMBEDDING_MODEL,
                content=content,
                task_type=task_type,
                output_dimensionality=settings.EMBEDDING_DIMENSIONS,
            )
        except TypeError:
            logger.warning("Gemini SDK ignored task_type or output_dimensionality; retrying with dimensions only.")
            result = genai.embed_content(
                model=settings.EMBEDDING_MODEL,
                content=content,
                output_dimensionality=settings.EMBEDDING_DIMENSIONS,
            )
    return _unwrap_gemini(result, expected=len(texts))


def _unwrap_gemini(result: object, *, expected: int) -> list[list[float]]:
    if isinstance(result, dict):
        embedding = result.get("embedding")
    else:
        embedding = getattr(result, "embedding", None)
    if not embedding:
        raise RuntimeError("Gemini returned no embeddings.")

    # A single input comes back as one vector. A batch comes back as a list of vectors.
    if isinstance(embedding[0], (int, float)):
        vectors = [embedding]
    else:
        vectors = embedding
    if len(vectors) != expected:
        raise RuntimeError(
            f"Gemini returned {len(vectors)} embeddings for {expected} inputs."
        )
    return [[float(value) for value in vector] for vector in vectors]


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
