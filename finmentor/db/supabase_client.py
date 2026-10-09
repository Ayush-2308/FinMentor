"""Supabase reads and writes.

Embeddings are sent as pgvector literals (`[0.1,0.2,...]`). PostgREST stores
that text in the vector(1536) column. The service-role key bypasses row-level
security, so it stays on the server.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client, ClientOptions, create_client

from auth import demo_enabled
from config import settings
from db import memory_store

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        # Service-role calls do not use a user session. A short timeout keeps a
        # dead database from holding the request open for the client default (120s).
        _client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY,
            options=ClientOptions(
                postgrest_client_timeout=20,
                auto_refresh_token=False,
                persist_session=False,
            ),
        )
    return _client


def vector_literal(values: list[float]) -> str:
    """Format a Python vector for a pgvector parameter or column."""
    if len(values) != settings.EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Expected {settings.EMBEDDING_DIMENSIONS} embedding dimensions, got {len(values)}. "
            "document_chunks.embedding is vector(1536)."
        )
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def insert_document(filename: str, doc_type_hint: Optional[str], user_id: str) -> dict[str, Any]:
    if demo_enabled():
        return memory_store.insert_document(filename, doc_type_hint, user_id)
    return _insert_document(filename, doc_type_hint, user_id)


def _insert_document(filename: str, doc_type_hint: Optional[str], user_id: str) -> dict[str, Any]:
    response = (
        get_client()
        .table("documents")
        .insert(
            {
                "filename": filename,
                "doc_type_hint": doc_type_hint,
                "status": "processing",
                "chunks_count": 0,
                "user_id": user_id,
            }
        )
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError("Supabase did not return the inserted document.")
    return rows[0]


def update_document(document_id: str, *, status: str, chunks_count: int) -> None:
    if demo_enabled():
        memory_store.update_document(document_id, status=status, chunks_count=chunks_count)
        return
    _update_document(document_id, status=status, chunks_count=chunks_count)


def _update_document(document_id: str, *, status: str, chunks_count: int) -> None:
    (
        get_client()
        .table("documents")
        .update({"status": status, "chunks_count": chunks_count})
        .eq("id", document_id)
        .execute()
    )


def get_document(document_id: str) -> Optional[dict[str, Any]]:
    if demo_enabled():
        return memory_store.get_document(document_id)
    return _get_document(document_id)


def _get_document(document_id: str) -> Optional[dict[str, Any]]:
    response = (
        get_client()
        .table("documents")
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_documents(user_id: str) -> list[dict[str, Any]]:
    if demo_enabled():
        return memory_store.list_documents(user_id)
    return _list_documents(user_id)


def _list_documents(user_id: str) -> list[dict[str, Any]]:
    response = (
        get_client()
        .table("documents")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def get_documents_by_ids(document_ids: list[str]) -> list[dict[str, Any]]:
    if not document_ids:
        return []
    if demo_enabled():
        return memory_store.get_documents_by_ids(document_ids)
    response = (
        get_client()
        .table("documents")
        .select("id, filename")
        .in_("id", document_ids)
        .execute()
    )
    return response.data or []


def delete_chunks(document_id: str) -> None:
    """Remove chunks so a failed index pass cannot be searched."""
    if demo_enabled():
        memory_store.delete_chunks(document_id)
        return
    _delete_chunks(document_id)


def _delete_chunks(document_id: str) -> None:
    get_client().table("document_chunks").delete().eq("document_id", document_id).execute()


def insert_chunks(
    document_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    if demo_enabled():
        memory_store.insert_chunks(document_id, chunks, embeddings)
        return
    _insert_chunks(document_id, chunks, embeddings)


def _insert_chunks(
    document_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("Chunk count and embedding count do not match.")

    rows: list[dict[str, Any]] = []
    for index, (text, embedding) in enumerate(zip(chunks, embeddings)):
        rows.append(
            {
                "document_id": document_id,
                "chunk_index": index,
                "chunk_text": text.replace("\x00", ""),
                "embedding": vector_literal(embedding),
            }
        )

    # Keep each request modest. A 1536-d vector is a long string.
    batch_size = 25
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        get_client().table("document_chunks").insert(batch).execute()
        logger.info(
            "Stored chunks %s-%s for document %s",
            start,
            start + len(batch) - 1,
            document_id,
        )


def match_document_chunks(
    query_embedding: list[float],
    *,
    match_count: int,
    document_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Call the match_document_chunks SQL function.

    Omitting filter_document_id searches every chunk that belongs to user_id.
    """
    if demo_enabled():
        return []
    payload: dict[str, Any] = {
        "query_embedding": vector_literal(query_embedding),
        "match_count": match_count,
    }
    if document_id is not None:
        payload["filter_document_id"] = document_id
    if user_id is not None:
        payload["filter_user_id"] = user_id

    response = get_client().rpc("match_document_chunks", payload).execute()
    matches: list[dict[str, Any]] = []
    for row in response.data or []:
        if row.get("similarity") is None:
            continue
        matches.append(
            {
                "id": row["id"],
                "document_id": row["document_id"],
                "chunk_text": row["chunk_text"],
                "similarity": float(row["similarity"]),
            }
        )
    return matches


def create_conversation(user_id: str, title: str) -> dict[str, Any]:
    response = (
        get_client()
        .table("conversations")
        .insert({"user_id": user_id, "title": title})
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError("Supabase did not return the conversation.")
    return rows[0]


def list_conversations(user_id: str) -> list[dict[str, Any]]:
    response = (
        get_client()
        .table("conversations")
        .select("id, title, updated_at")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    rows = response.data or []
    for row in rows:
        preview = (
            get_client()
            .table("messages")
            .select("content")
            .eq("conversation_id", row["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        items = preview.data or []
        row["preview"] = items[0]["content"] if items else None
    return rows


def get_conversation(conversation_id: str, user_id: str) -> Optional[dict[str, Any]]:
    response = (
        get_client()
        .table("conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    response = (
        get_client()
        .table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    return response.data or []


def add_message(
    conversation_id: str,
    user_id: str,
    *,
    role: str,
    content: str,
    grounded: Optional[bool] = None,
    sources: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    response = (
        get_client()
        .table("messages")
        .insert(
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "grounded": grounded,
                "sources": sources or [],
            }
        )
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError("Supabase did not return the message.")
    patch: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if role == "user":
        existing = get_conversation(conversation_id, user_id)
        if existing and existing.get("title") == "New chat":
            patch["title"] = content.strip()[:56]
    (
        get_client()
        .table("conversations")
        .update(patch)
        .eq("id", conversation_id)
        .execute()
    )
    return rows[0]


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    existing = get_conversation(conversation_id, user_id)
    if existing is None:
        return False
    get_client().table("conversations").delete().eq("id", conversation_id).eq("user_id", user_id).execute()
    return True


def log_query(
    *,
    query_text: str,
    document_id: Optional[str],
    answer: str,
    retrieved_chunk_ids: list[str],
) -> None:
    if demo_enabled():
        return
    _log_query(
        query_text=query_text,
        document_id=document_id,
        answer=answer,
        retrieved_chunk_ids=retrieved_chunk_ids,
    )


def _log_query(
    *,
    query_text: str,
    document_id: Optional[str],
    answer: str,
    retrieved_chunk_ids: list[str],
) -> None:
    (
        get_client()
        .table("queries_log")
        .insert(
            {
                "query_text": query_text,
                "document_id": document_id,
                "answer": answer,
                "retrieved_chunk_ids": retrieved_chunk_ids,
            }
        )
        .execute()
    )
