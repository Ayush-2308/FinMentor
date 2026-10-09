"""Load the environment and refuse to start when it is incomplete.

Every name in .env.example is required. Importing this module builds `settings`
immediately so a missing value fails at process start, before a request is served.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent

# Package .env wins. A repo-root .env fills anything still unset. Existing
# process environment variables are left alone so a host can inject secrets.
load_dotenv(PACKAGE_DIR / ".env")
load_dotenv(PACKAGE_DIR.parent / ".env")
load_dotenv()

REQUIRED_VARS = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_ANON_KEY",
    "OCR_API_KEY",
    "OCR_ENDPOINT",
    "OCR_PROVIDER",
    "LLM_API_KEY",
    "LLM_PROVIDER",
    "EMBEDDING_API_KEY",
    "EMBEDDING_PROVIDER",
    "SIMILARITY_TOP_K",
    "SIMILARITY_THRESHOLD",
)

LLM_PROVIDERS = frozenset({"gemini", "openai", "anthropic"})
EMBEDDING_PROVIDERS = frozenset({"openai", "gemini"})

# Column document_chunks.embedding is vector(1536). These defaults match that.
EMBEDDING_DIMENSIONS = 1536
LLM_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
}
EMBEDDING_MODELS = {
    "openai": "text-embedding-3-small",
    "gemini": "models/gemini-embedding-001",
}

# google.generativeai keeps the API key in process-global state. Embedding and
# chat calls can use different keys, so they must not configure the SDK at once.
gemini_configure_lock = threading.Lock()


def _required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            "Copy finmentor/.env.example to finmentor/.env and set every variable."
        )
    return value.strip()


class Settings:
    """Typed view of the required environment."""

    def __init__(self) -> None:
        missing = [name for name in REQUIRED_VARS if not (os.getenv(name) or "").strip()]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                "Missing required environment variables: "
                f"{joined}. Copy finmentor/.env.example to finmentor/.env and set every variable."
            )

        self.SUPABASE_URL = _required("SUPABASE_URL")
        self.SUPABASE_KEY = _required("SUPABASE_KEY")
        # Anon key, not the service role. Signup and OTP must use it or Supabase
        # auto-confirms the account and never sends a verification code.
        self.SUPABASE_ANON_KEY = _required("SUPABASE_ANON_KEY")
        self.OCR_API_KEY = _required("OCR_API_KEY")
        self.OCR_ENDPOINT = _required("OCR_ENDPOINT")
        self.OCR_PROVIDER = _required("OCR_PROVIDER").lower()
        self.LLM_API_KEY = _required("LLM_API_KEY")
        self.LLM_PROVIDER = _required("LLM_PROVIDER").lower()
        self.EMBEDDING_API_KEY = _required("EMBEDDING_API_KEY")
        self.EMBEDDING_PROVIDER = _required("EMBEDDING_PROVIDER").lower()

        if self.OCR_PROVIDER != "mistral":
            raise RuntimeError("OCR_PROVIDER must be mistral. This build calls the Mistral OCR API.")
        if self.LLM_PROVIDER not in LLM_PROVIDERS:
            raise RuntimeError("LLM_PROVIDER must be one of: gemini, openai, anthropic")
        if self.EMBEDDING_PROVIDER not in EMBEDDING_PROVIDERS:
            raise RuntimeError("EMBEDDING_PROVIDER must be one of: openai, gemini")

        try:
            self.SIMILARITY_TOP_K = int(_required("SIMILARITY_TOP_K"))
        except ValueError as exc:
            raise RuntimeError("SIMILARITY_TOP_K must be an integer.") from exc
        if self.SIMILARITY_TOP_K < 1:
            raise RuntimeError("SIMILARITY_TOP_K must be a positive integer.")

        try:
            self.SIMILARITY_THRESHOLD = float(_required("SIMILARITY_THRESHOLD"))
        except ValueError as exc:
            raise RuntimeError("SIMILARITY_THRESHOLD must be a number.") from exc
        if not 0.0 <= self.SIMILARITY_THRESHOLD <= 1.0:
            raise RuntimeError("SIMILARITY_THRESHOLD must be between 0 and 1.")

        self.LLM_MODEL = LLM_MODELS[self.LLM_PROVIDER]
        self.EMBEDDING_MODEL = EMBEDDING_MODELS[self.EMBEDDING_PROVIDER]
        self.EMBEDDING_DIMENSIONS = EMBEDDING_DIMENSIONS


settings = Settings()
