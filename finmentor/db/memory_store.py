"""In-process chat history for the local dummy account.

Used when SUPABASE_URL is still a placeholder so history works without Postgres.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

_lock = threading.Lock()
_conversations: dict[str, dict[str, Any]] = {}
_messages: dict[str, list[dict[str, Any]]] = {}
_documents: dict[str, dict[str, Any]] = {}
_chunks: dict[str, list[dict[str, Any]]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_conversation(user_id: str, title: str) -> dict[str, Any]:
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "title": title,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        _conversations[row["id"]] = row
        _messages[row["id"]] = []
    return row


def list_conversations(user_id: str) -> list[dict[str, Any]]:
    with _lock:
        rows = [dict(row) for row in _conversations.values() if row["user_id"] == user_id]
        for row in rows:
            msgs = _messages.get(row["id"]) or []
            row["preview"] = msgs[-1]["content"] if msgs else None
    rows.sort(key=lambda item: item["updated_at"], reverse=True)
    return rows


def get_conversation(conversation_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        row = _conversations.get(conversation_id)
        if row is None or row["user_id"] != user_id:
            return None
        return dict(row)


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _messages.get(conversation_id) or []]


def add_message(
    conversation_id: str,
    user_id: str,
    *,
    role: str,
    content: str,
    grounded: Optional[bool] = None,
    sources: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    row = {
        "id": str(uuid4()),
        "conversation_id": conversation_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "grounded": grounded,
        "sources": sources or [],
        "created_at": _now(),
    }
    with _lock:
        _messages.setdefault(conversation_id, []).append(row)
        convo = _conversations.get(conversation_id)
        if convo:
            convo["updated_at"] = _now()
            if role == "user" and convo["title"] == "New chat":
                convo["title"] = content.strip()[:56]
    return row


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    with _lock:
        row = _conversations.get(conversation_id)
        if row is None or row["user_id"] != user_id:
            return False
        del _conversations[conversation_id]
        _messages.pop(conversation_id, None)
    return True


def insert_document(filename: str, doc_type_hint: Optional[str], user_id: str) -> dict[str, Any]:
    row = {
        "id": str(uuid4()),
        "filename": filename,
        "doc_type_hint": doc_type_hint,
        "status": "processing",
        "chunks_count": 0,
        "user_id": user_id,
        "created_at": _now(),
    }
    with _lock:
        _documents[row["id"]] = row
        _chunks[row["id"]] = []
    return dict(row)


def list_documents(user_id: str) -> list[dict[str, Any]]:
    with _lock:
        rows = [dict(row) for row in _documents.values() if row["user_id"] == user_id]
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    return rows


def get_document(document_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        row = _documents.get(document_id)
        return dict(row) if row else None


def get_documents_by_ids(document_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(document_ids)
    with _lock:
        return [dict(row) for doc_id, row in _documents.items() if doc_id in wanted]


def update_document(document_id: str, *, status: str, chunks_count: int) -> None:
    with _lock:
        row = _documents.get(document_id)
        if row:
            row["status"] = status
            row["chunks_count"] = chunks_count


def delete_chunks(document_id: str) -> None:
    with _lock:
        _chunks[document_id] = []


def insert_chunks(document_id: str, chunks: list[str], embeddings: list[list[float]]) -> None:
    rows = []
    for index, text in enumerate(chunks):
        rows.append(
            {
                "id": str(uuid4()),
                "document_id": document_id,
                "chunk_index": index,
                "chunk_text": text,
            }
        )
    with _lock:
        _chunks[document_id] = rows
    del embeddings


def match_text(
    query: str,
    *,
    match_count: int,
    document_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Word overlap instead of vectors, so demo login can retrieve without API keys."""
    terms = {word.lower() for word in query.split() if len(word) > 2}
    scored: list[dict[str, Any]] = []
    with _lock:
        for doc_id, chunks in _chunks.items():
            doc = _documents.get(doc_id)
            if doc is None:
                continue
            if user_id and doc["user_id"] != user_id:
                continue
            if document_id and doc_id != document_id:
                continue
            for chunk in chunks:
                words = {word.lower() for word in chunk["chunk_text"].split() if len(word) > 2}
                if not terms:
                    continue
                overlap = len(terms & words) / len(terms)
                if overlap <= 0:
                    continue
                scored.append(
                    {
                        "id": chunk["id"],
                        "document_id": doc_id,
                        "chunk_text": chunk["chunk_text"],
                        "similarity": min(0.99, 0.78 + overlap * 0.2),
                    }
                )
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:match_count]


def clear_user(user_id: str) -> None:
    with _lock:
        ids = [key for key, row in _conversations.items() if row["user_id"] == user_id]
        for key in ids:
            del _conversations[key]
            _messages.pop(key, None)
