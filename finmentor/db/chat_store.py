"""Conversations and messages: memory for demo, Supabase otherwise."""

from __future__ import annotations

from typing import Any, Optional

from auth import demo_enabled
from db import memory_store, supabase_client


def create_conversation(user_id: str, title: str = "New chat") -> dict[str, Any]:
    if demo_enabled():
        return memory_store.create_conversation(user_id, title)
    return supabase_client.create_conversation(user_id, title)


def list_conversations(user_id: str) -> list[dict[str, Any]]:
    if demo_enabled():
        return memory_store.list_conversations(user_id)
    return supabase_client.list_conversations(user_id)


def get_conversation(conversation_id: str, user_id: str) -> Optional[dict[str, Any]]:
    if demo_enabled():
        return memory_store.get_conversation(conversation_id, user_id)
    return supabase_client.get_conversation(conversation_id, user_id)


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    if demo_enabled():
        return memory_store.list_messages(conversation_id)
    return supabase_client.list_messages(conversation_id)


def add_message(
    conversation_id: str,
    user_id: str,
    *,
    role: str,
    content: str,
    grounded: Optional[bool] = None,
    sources: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    if demo_enabled():
        return memory_store.add_message(
            conversation_id,
            user_id,
            role=role,
            content=content,
            grounded=grounded,
            sources=sources,
        )
    return supabase_client.add_message(
        conversation_id,
        user_id,
        role=role,
        content=content,
        grounded=grounded,
        sources=sources,
    )


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    if demo_enabled():
        return memory_store.delete_conversation(conversation_id, user_id)
    return supabase_client.delete_conversation(conversation_id, user_id)
