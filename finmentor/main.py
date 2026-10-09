"""FinMentor HTTP API and static UI.

Upload returns as soon as the document row exists. OCR, chunking, and
embedding run afterward so a slow scan does not hold the HTTP connection open.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from auth import AuthError, demo_enabled, fetch_user, logout, refresh_session, send_otp, sign_in, sign_up, verify_code
from config import settings
from db import chat_store, supabase_client
from pipeline.chunking import split_text
from pipeline.embeddings import embed_texts
from pipeline.ocr import extract_text
from pipeline.retrieval import LLMError, answer_query
from schemas.models import (
    STATUS_FAILED,
    STATUS_INDEXED,
    STATUS_PROCESSING,
    DOC_TYPE_PRESETS,
    MAX_CUSTOM_TYPE_CHARS,
    PRESET_DOC_TYPES,
    AuthResult,
    AuthStart,
    ChatMessage,
    ConversationDetail,
    ConversationSummary,
    DocTypeOption,
    DocumentMeta,
    DocumentUploadResponse,
    HealthResponse,
    OtpStart,
    QueryRequest,
    QueryResponse,
    RefreshSession,
    SourceChunk,
    VerifyCode,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".txt"})

app = FastAPI(
    title="FinMentor",
    version="1.0.0",
    description="Grounded question answering over uploaded personal-finance documents.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        ocr_provider=settings.OCR_PROVIDER,
        llm_provider=settings.LLM_PROVIDER,
        llm_model=settings.LLM_MODEL,
        embedding_provider=settings.EMBEDDING_PROVIDER,
        embedding_model=settings.EMBEDDING_MODEL,
        similarity_top_k=settings.SIMILARITY_TOP_K,
        similarity_threshold=settings.SIMILARITY_THRESHOLD,
    )


def require_user(authorization: Optional[str] = Header(None)) -> str:
    """Resolve the signed-in Supabase user from the bearer token."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        user = fetch_user(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return str(user["id"])


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@app.post("/auth/signup", response_model=AuthResult)
def auth_signup(body: AuthStart) -> AuthResult:
    return _auth_call(lambda: sign_up(channel=body.channel, email=body.email, phone=body.phone, password=body.password))


@app.post("/auth/login", response_model=AuthResult)
def auth_login(body: AuthStart) -> AuthResult:
    return _auth_call(lambda: sign_in(channel=body.channel, email=body.email, phone=body.phone, password=body.password))


@app.post("/auth/otp", response_model=AuthResult)
def auth_otp(body: OtpStart) -> AuthResult:
    return _auth_call(
        lambda: send_otp(
            channel=body.channel,
            email=body.email,
            phone=body.phone,
            create_user=body.create_user,
        )
    )


@app.post("/auth/verify", response_model=AuthResult)
def auth_verify(body: VerifyCode) -> AuthResult:
    return _auth_call(
        lambda: verify_code(
            channel=body.channel,
            email=body.email,
            phone=body.phone,
            token=body.token,
            verification_type=body.verification_type,
        )
    )


@app.post("/auth/refresh", response_model=AuthResult)
def auth_refresh(body: RefreshSession) -> AuthResult:
    return _auth_call(lambda: refresh_session(body.refresh_token))


@app.post("/auth/logout", status_code=204)
def auth_logout(authorization: Optional[str] = Header(None)) -> Response:
    token = _bearer(authorization)
    if token:
        logout(token)
    return Response(status_code=204)


@app.get("/doc-types", response_model=list[DocTypeOption])
def doc_types() -> list[DocTypeOption]:
    return [DocTypeOption(value=slug, label=label) for slug, label in DOC_TYPE_PRESETS]


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user_id: str = Depends(require_user)) -> list[ConversationSummary]:
    try:
        rows = chat_store.list_conversations(user_id)
    except Exception as exc:
        logger.exception("Could not list conversations")
        raise _db_http_error(exc, fallback="Could not load chat history. Run finmentor/db/migrations_chat.sql.") from exc
    return [
        ConversationSummary(
            id=row["id"],
            title=row.get("title") or "New chat",
            updated_at=row["updated_at"],
            preview=row.get("preview"),
        )
        for row in rows
    ]


@app.post("/conversations", response_model=ConversationSummary)
def create_conversation(user_id: str = Depends(require_user)) -> ConversationSummary:
    try:
        row = chat_store.create_conversation(user_id, "New chat")
    except Exception as exc:
        logger.exception("Could not create conversation")
        raise _db_http_error(exc, fallback="Could not start a chat. Run finmentor/db/migrations_chat.sql.") from exc
    return ConversationSummary(
        id=row["id"],
        title=row.get("title") or "New chat",
        updated_at=row["updated_at"],
        preview=None,
    )


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: UUID, user_id: str = Depends(require_user)) -> ConversationDetail:
    try:
        row = chat_store.get_conversation(str(conversation_id), user_id)
    except Exception as exc:
        logger.exception("Could not load conversation")
        raise _db_http_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    messages = chat_store.list_messages(str(conversation_id))
    return ConversationDetail(
        id=row["id"],
        title=row.get("title") or "New chat",
        messages=[_to_message(item) for item in messages],
    )


@app.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, user_id: str = Depends(require_user)) -> Response:
    try:
        found = chat_store.delete_conversation(str(conversation_id), user_id)
    except Exception as exc:
        logger.exception("Could not delete conversation")
        raise _db_http_error(exc) from exc
    if not found:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return Response(status_code=204)


@app.get("/documents", response_model=list[DocumentMeta])
def list_documents(user_id: str = Depends(require_user)) -> list[DocumentMeta]:
    try:
        rows = supabase_client.list_documents(user_id)
    except Exception as exc:
        logger.exception("Could not list documents")
        raise _db_http_error(exc) from exc
    return [_to_meta(row) for row in rows]


@app.get("/documents/{document_id}", response_model=DocumentMeta)
def get_document(document_id: UUID, user_id: str = Depends(require_user)) -> DocumentMeta:
    try:
        row = supabase_client.get_document(str(document_id))
    except Exception as exc:
        logger.exception("Could not load document %s", document_id)
        raise _db_http_error(exc) from exc
    if row is None or str(row.get("user_id") or "") != user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _to_meta(row)


@app.post("/upload", response_model=DocumentUploadResponse, status_code=202)
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type_hint: Optional[str] = Form(None),
    user_id: str = Depends(require_user),
) -> DocumentUploadResponse:
    filename = _safe_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF, text file, or image (png, jpg, webp, tiff).",
        )

    hint = _normalize_doc_type(doc_type_hint)
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="File is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB.")

    temp_path = _write_temp(payload, suffix)
    try:
        row = supabase_client.insert_document(filename, hint, user_id)
    except Exception as exc:
        _remove_temp(temp_path)
        logger.exception("Could not create document row")
        raise _db_http_error(exc) from exc

    document_id = str(row["id"])
    background_tasks.add_task(_index_uploaded_file, document_id, temp_path, filename)
    return DocumentUploadResponse(document_id=row["id"], status=STATUS_PROCESSING, chunks_count=None)


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, user_id: str = Depends(require_user)) -> QueryResponse:
    document_id = str(body.document_id) if body.document_id else None
    if document_id is not None:
        _require_indexed(document_id, user_id)
    conversation_id = str(body.conversation_id) if body.conversation_id else None
    if conversation_id:
        existing = chat_store.get_conversation(conversation_id, user_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
    else:
        started = chat_store.create_conversation(user_id, body.query[:56])
        conversation_id = str(started["id"])
    try:
        result = answer_query(body.query, document_id, user_id)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Query failed")
        raise _db_http_error(exc, fallback="Could not answer that question.") from exc

    sources = [chunk.model_dump(mode="json") for chunk in result.sources]
    chat_store.add_message(conversation_id, user_id, role="user", content=body.query)
    chat_store.add_message(
        conversation_id,
        user_id,
        role="assistant",
        content=result.answer,
        grounded=result.grounded,
        sources=sources,
    )
    return result.model_copy(update={"conversation_id": conversation_id})


def _index_uploaded_file(document_id: str, temp_path: str, filename: str) -> None:
    """OCR, chunk, embed, and store. Runs after the upload response is sent."""
    try:
        text = extract_text(temp_path, filename)
        chunks = split_text(text)
        if not chunks:
            raise ValueError("No text chunks were produced from the document.")
        if demo_enabled():
            vectors = [[] for _ in chunks]
        else:
            vectors = embed_texts(chunks, task="document")
        # Drop any earlier attempt before inserting, so a retry cannot duplicate chunks.
        supabase_client.delete_chunks(document_id)
        supabase_client.insert_chunks(document_id, chunks, vectors)
        supabase_client.update_document(
            document_id,
            status=STATUS_INDEXED,
            chunks_count=len(chunks),
        )
        logger.info("Indexed document %s with %s chunk(s)", document_id, len(chunks))
    except Exception:
        logger.exception("Indexing failed for document %s", document_id)
        _mark_failed(document_id)
    finally:
        _remove_temp(temp_path)


def _mark_failed(document_id: str) -> None:
    try:
        supabase_client.delete_chunks(document_id)
        supabase_client.update_document(document_id, status=STATUS_FAILED, chunks_count=0)
    except Exception:
        logger.exception("Could not mark document %s as failed", document_id)


def _auth_call(action):
    try:
        return AuthResult(**action())
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _db_http_error(exc: Exception, fallback: str = "Database request failed.") -> HTTPException:
    text = str(exc).lower()
    if "user_id" in text or "filter_user_id" in text or "conversations" in text:
        return HTTPException(
            status_code=503,
            detail="Run finmentor/db/migrations_auth.sql in the Supabase SQL editor, then retry.",
        )
    return HTTPException(status_code=502, detail=fallback)


def _require_indexed(document_id: str, user_id: str) -> None:
    try:
        row = supabase_client.get_document(document_id)
    except Exception as exc:
        logger.exception("Could not load document %s before query", document_id)
        raise _db_http_error(exc) from exc
    if row is None or str(row.get("user_id") or "") != user_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    status = row.get("status")
    if status == STATUS_PROCESSING:
        raise HTTPException(
            status_code=409,
            detail="That document is still being indexed. Try again in a moment.",
        )
    if status == STATUS_FAILED:
        raise HTTPException(
            status_code=409,
            detail="That document failed to index. Upload it again.",
        )


def _to_meta(row: dict) -> DocumentMeta:
    return DocumentMeta(
        id=row["id"],
        filename=row["filename"],
        doc_type_hint=row.get("doc_type_hint"),
        status=row.get("status") or STATUS_PROCESSING,
        chunks_count=row.get("chunks_count") or 0,
        created_at=row["created_at"],
    )


def _normalize_doc_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return None
    if cleaned in PRESET_DOC_TYPES:
        return cleaned
    if len(cleaned) < 2 or len(cleaned) > MAX_CUSTOM_TYPE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Custom type must be 2–{MAX_CUSTOM_TYPE_CHARS} characters.",
        )
    return cleaned


def _to_message(row: dict) -> ChatMessage:
    raw_sources = row.get("sources") or []
    sources = []
    for item in raw_sources:
        try:
            sources.append(SourceChunk.model_validate(item))
        except Exception:
            continue
    return ChatMessage(
        id=row["id"],
        role=row["role"],
        content=row["content"],
        grounded=row.get("grounded"),
        sources=sources,
        created_at=row["created_at"],
    )


def _safe_filename(filename: Optional[str]) -> str:
    name = Path(filename or "upload").name.strip()
    if not name or name in {".", ".."}:
        name = "upload"
    return name[:255]


def _write_temp(payload: bytes, suffix: str) -> str:
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return temp_path


def _remove_temp(temp_path: str) -> None:
    try:
        os.remove(temp_path)
    except OSError:
        logger.warning("Could not delete temp file %s", temp_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
