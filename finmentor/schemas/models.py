"""Request and response models.

The document and query models follow schemas_reference.py. HealthResponse is
added for GET /health. Field names are part of the API contract.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

# Stored on documents.status. The UI polls until the value leaves "processing".
STATUS_PROCESSING = "processing"
STATUS_INDEXED = "indexed"
STATUS_FAILED = "failed"

DOC_TYPE_PRESETS: list[tuple[str, str]] = [
    ("bank_statement", "Bank statement"),
    ("insurance_policy", "Insurance policy"),
    ("investment_record", "Investment / portfolio"),
    ("grocery_bill", "Grocery bill"),
    ("electricity_bill", "Electricity bill"),
    ("water_bill", "Water bill"),
    ("gas_bill", "Gas / PNG bill"),
    ("mobile_bill", "Mobile / broadband bill"),
    ("rent_receipt", "Rent receipt"),
    ("salary_slip", "Salary slip"),
    ("form_16", "Form 16 / tax"),
    ("credit_card_statement", "Credit-card statement"),
    ("loan_emi_statement", "Loan / EMI statement"),
    ("mutual_fund_sip", "Mutual fund / SIP"),
    ("demat_statement", "Demat / brokerage"),
    ("medical_bill", "Medical / hospital bill"),
    ("fuel_bill", "Fuel / petrol bill"),
    ("travel_receipt", "Travel / booking"),
    ("utility_bill", "Other utility bill"),
]
PRESET_DOC_TYPES = frozenset(slug for slug, _ in DOC_TYPE_PRESETS)
MAX_CUSTOM_TYPE_CHARS = 60

# Returned when retrieval finds nothing at or above SIMILARITY_THRESHOLD.
# The LLM is not called in that case.
NO_MATCH_ANSWER = "I couldn't find relevant information in your uploaded documents"

MAX_QUERY_CHARS = 2000


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    status: str  # "processing" | "indexed" | "failed"
    chunks_count: Optional[int] = None


class DocumentMeta(BaseModel):
    id: UUID
    filename: str
    doc_type_hint: Optional[str] = None
    status: str
    chunks_count: int
    created_at: datetime


class QueryRequest(BaseModel):
    query: str
    document_id: Optional[UUID] = None  # if None, search across all documents
    conversation_id: Optional[UUID] = None  # if None, start a new chat

    @field_validator("query")
    @classmethod
    def query_must_be_usable(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        if len(cleaned) > MAX_QUERY_CHARS:
            raise ValueError(f"query must be {MAX_QUERY_CHARS} characters or fewer")
        return cleaned


class SourceChunk(BaseModel):
    document_id: UUID
    chunk_text: str
    similarity_score: float


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceChunk]
    grounded: bool  # False if no chunk passed the similarity threshold
    conversation_id: Optional[UUID] = None


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    preview: Optional[str] = None


class ChatMessage(BaseModel):
    id: UUID
    role: str
    content: str
    grounded: Optional[bool] = None
    sources: List[SourceChunk] = []
    created_at: datetime


class ConversationDetail(BaseModel):
    id: UUID
    title: str
    messages: List[ChatMessage]


class DocTypeOption(BaseModel):
    value: str
    label: str


class AuthStart(BaseModel):
    """Email or phone, with a password. Used for both signup and login."""

    channel: str  # "email" | "phone"
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str

    @field_validator("channel")
    @classmethod
    def channel_known(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"email", "phone"}:
            raise ValueError("channel must be email or phone")
        return cleaned

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("password must be at least 8 characters")
        return value

    @model_validator(mode="after")
    def contact_matches_channel(self):
        if self.channel == "email" and not (self.email or "").strip():
            raise ValueError("email is required")
        if self.channel == "phone" and not (self.phone or "").strip():
            raise ValueError("phone is required")
        return self


class OtpStart(BaseModel):
    """Passwordless code. Signup creates the account; login does not."""

    channel: str
    email: Optional[str] = None
    phone: Optional[str] = None
    create_user: bool = False

    @field_validator("channel")
    @classmethod
    def channel_known(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"email", "phone"}:
            raise ValueError("channel must be email or phone")
        return cleaned

    @model_validator(mode="after")
    def contact_matches_channel(self):
        if self.channel == "email" and not (self.email or "").strip():
            raise ValueError("email is required")
        if self.channel == "phone" and not (self.phone or "").strip():
            raise ValueError("phone is required")
        return self


class VerifyCode(BaseModel):
    channel: str
    email: Optional[str] = None
    phone: Optional[str] = None
    token: str
    verification_type: str  # signup | email | sms

    @field_validator("token")
    @classmethod
    def token_digits(cls, value: str) -> str:
        cleaned = value.strip().replace(" ", "")
        if not cleaned.isdigit() or not 6 <= len(cleaned) <= 10:
            raise ValueError("Enter the verification code")
        return cleaned


class RefreshSession(BaseModel):
    refresh_token: str


class AuthResult(BaseModel):
    status: str  # "authenticated" | "verification_required"
    channel: str
    destination: str
    verification_type: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user_id: Optional[UUID] = None


class HealthResponse(BaseModel):
    """Provider and model info. Does not call Supabase or the LLM."""

    status: str
    ocr_provider: str
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    similarity_top_k: int
    similarity_threshold: float
