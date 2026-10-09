"""Split extracted text into overlapping chunks for embedding.

Chunk size and overlap are fixed so a figure near a boundary still appears in
the neighboring chunk. LangChain's recursive splitter prefers paragraph and
line breaks before it cuts mid-sentence.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)


def split_text(text: str) -> list[str]:
    """Return non-empty chunks. Postgres cannot store NUL bytes."""
    cleaned = text.replace("\x00", "").strip()
    if not cleaned:
        return []
    chunks = _splitter.split_text(cleaned)
    return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]
