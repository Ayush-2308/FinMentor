"""Turn an uploaded file into plain text.

PDF and image bytes are base64-encoded and posted to OCR_ENDPOINT (Mistral).
Plain-text uploads are decoded locally so the fictional sample files can be
indexed without sending them to OCR.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})
MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

OCR_MODEL = "mistral-ocr-latest"
OCR_TIMEOUT_SECONDS = 120.0


def extract_text(path: str, filename: str) -> str:
    """Return the document text for chunking."""
    raw = Path(path).read_bytes()
    if not raw:
        raise ValueError("The uploaded file is empty.")

    suffix = Path(filename).suffix.lower()
    if suffix == ".txt" and not raw.startswith(b"%PDF"):
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            raise ValueError("The text file has no readable text.")
        return text

    # A .txt file that is actually a PDF still goes through OCR.
    ocr_name = filename if suffix != ".txt" else str(Path(filename).with_suffix(".pdf"))
    text = _mistral_ocr(raw, ocr_name)
    if not text:
        raise ValueError("OCR returned no text.")
    return text


def _mistral_ocr(raw: bytes, filename: str) -> str:
    payload = {
        "model": OCR_MODEL,
        "document": _document_body(raw, filename),
        # Statements and portfolios are tables. Markdown keeps rows together
        # better than a flat stream of cells.
        "table_format": "markdown",
        "include_image_base64": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.OCR_API_KEY}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=OCR_TIMEOUT_SECONDS) as client:
        response = client.post(settings.OCR_ENDPOINT, headers=headers, json=payload)

    if response.status_code >= 400:
        # The body is an API error, not the uploaded document. Keep it short.
        detail = response.text[:500]
        raise RuntimeError(f"Mistral OCR returned HTTP {response.status_code}: {detail}")

    pages = response.json().get("pages") or []
    parts: list[str] = []
    for page in pages:
        markdown = (page.get("markdown") or page.get("text") or "").strip()
        if markdown:
            parts.append(markdown)
    logger.info("OCR extracted %s page(s) from %s", len(parts), filename)
    return "\n\n".join(parts).strip()


def _document_body(raw: bytes, filename: str) -> dict[str, str]:
    suffix = Path(filename).suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix, "application/pdf")
    encoded = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    if suffix in IMAGE_SUFFIXES:
        return {"type": "image_url", "image_url": data_url}
    return {"type": "document_url", "document_url": data_url}
