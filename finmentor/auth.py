"""Signup, login, and one-time codes through Supabase Auth.

Calls use the anon key. The service-role key would auto-confirm the user and
skip the email or SMS the verification screen is waiting on.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")

_TIMEOUT = 20.0

# Local dummy account. Used when Supabase is still a placeholder, so the UI
# can be opened without a real project.
DEMO_EMAIL = "demo@finmentor.app"
DEMO_PASSWORD = "Demo@12345"
DEMO_PHONE = "+919800000001"
DEMO_USER_ID = "00000000-0000-4000-a000-000000000001"
DEMO_TOKEN = "demo.finmentor.local"


def demo_enabled() -> bool:
    url = settings.SUPABASE_URL.lower()
    return "example.supabase.co" in url or "your-project.supabase.co" in url


def _demo_session() -> dict[str, Any]:
    return {
        "status": "authenticated",
        "channel": "email",
        "destination": DEMO_EMAIL,
        "verification_type": None,
        "access_token": DEMO_TOKEN,
        "refresh_token": DEMO_TOKEN,
        "user_id": DEMO_USER_ID,
    }


def _is_demo_password(channel: str, email: Optional[str], phone: Optional[str], password: str) -> bool:
    if not demo_enabled() or password != DEMO_PASSWORD:
        return False
    if channel == "email":
        return (email or "").strip().lower() == DEMO_EMAIL
    return re.sub(r"[\s()-]", "", phone or "") == DEMO_PHONE


class AuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def sign_up(*, channel: str, email: Optional[str], phone: Optional[str], password: str) -> dict[str, Any]:
    if _is_demo_password(channel, email, phone, password):
        return _demo_session()
    contact = _contact(channel, email, phone)
    body: dict[str, Any] = {"password": password, channel: contact}
    if channel == "phone":
        body["channel"] = "sms"
    data = _request("POST", "/signup", body)
    session = _session(data)
    if session:
        return _authenticated(channel, contact, session, data.get("user") or data)
    # No session means Supabase is holding the account until the code is entered.
    return _pending(channel, contact, "signup" if channel == "email" else "sms")


def sign_in(*, channel: str, email: Optional[str], phone: Optional[str], password: str) -> dict[str, Any]:
    if _is_demo_password(channel, email, phone, password):
        return _demo_session()
    contact = _contact(channel, email, phone)
    try:
        data = _request(
            "POST",
            "/token?grant_type=password",
            {"password": password, channel: contact},
        )
    except AuthError as exc:
        if _needs_confirmation(str(exc)):
            _resend(channel, contact, "signup" if channel == "email" else "sms")
            return _pending(channel, contact, "signup" if channel == "email" else "sms")
        raise
    session = _session(data)
    if not session:
        raise AuthError("Sign-in did not return a session. Check the code we sent.", status_code=401)
    return _authenticated(channel, contact, session, data.get("user") or data)


def send_otp(*, channel: str, email: Optional[str], phone: Optional[str], create_user: bool) -> dict[str, Any]:
    contact = _contact(channel, email, phone)
    body: dict[str, Any] = {channel: contact, "create_user": create_user}
    if channel == "phone":
        body["channel"] = "sms"
    _request("POST", "/otp", body)
    verification_type = "sms" if channel == "phone" else "email"
    return _pending(channel, contact, verification_type)


def verify_code(
    *,
    channel: str,
    email: Optional[str],
    phone: Optional[str],
    token: str,
    verification_type: str,
) -> dict[str, Any]:
    contact = _contact(channel, email, phone)
    allowed = {"signup", "email", "sms", "magiclink"}
    if verification_type not in allowed:
        raise AuthError("Unknown verification type.")
    data = _request(
        "POST",
        "/verify",
        {"type": verification_type, "token": token, channel: contact},
    )
    session = _session(data)
    if not session:
        raise AuthError("That code did not sign you in. Request a new one.")
    return _authenticated(channel, contact, session, data.get("user") or data)


def refresh_session(refresh_token: str) -> dict[str, Any]:
    token = refresh_token.strip()
    if not token:
        raise AuthError("Missing refresh token.", status_code=401)
    if demo_enabled() and token == DEMO_TOKEN:
        return _demo_session()
    data = _request("POST", "/token?grant_type=refresh_token", {"refresh_token": token})
    session = _session(data)
    if not session:
        raise AuthError("Session expired. Sign in again.", status_code=401)
    user = data.get("user") or {}
    channel = "phone" if user.get("phone") else "email"
    contact = user.get("phone") or user.get("email") or ""
    return _authenticated(channel, contact, session, user)


def fetch_user(access_token: str) -> dict[str, Any]:
    if demo_enabled() and access_token == DEMO_TOKEN:
        return {"id": DEMO_USER_ID, "email": DEMO_EMAIL}
    data = _request("GET", "/user", token=access_token)
    user_id = data.get("id")
    if not user_id:
        raise AuthError("Sign in to continue.", status_code=401)
    return data


def logout(access_token: str) -> None:
    try:
        _request("POST", "/logout", {}, token=access_token)
    except AuthError:
        logger.info("Logout call did not revoke the token; the client will drop it locally.")


def _resend(channel: str, contact: str, verification_type: str) -> None:
    try:
        _request("POST", "/resend", {"type": verification_type, channel: contact})
    except AuthError:
        logger.info("Could not resend a confirmation code for %s", _mask(channel, contact))


def _request(method: str, path: str, body: Optional[dict[str, Any]] = None, token: Optional[str] = None) -> dict[str, Any]:
    headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token or settings.SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    url = settings.SUPABASE_URL.rstrip("/") + "/auth/v1" + path
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.request(method, url, headers=headers, json=body if method != "GET" else None)
    except httpx.HTTPError as exc:
        logger.warning("Auth service unreachable: %s", exc.__class__.__name__)
        raise AuthError("Could not reach the sign-in service.", status_code=502) from exc

    if response.status_code >= 400:
        message = _error_message(response)
        status = 401 if response.status_code in {400, 401, 403} and "confirm" not in message.lower() else response.status_code
        if response.status_code == 429:
            status = 429
        if _needs_confirmation(message):
            status = 400
        raise AuthError(_friendly(message), status_code=status)
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {}


def _session(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    if data.get("access_token"):
        return data
    nested = data.get("session")
    if isinstance(nested, dict) and nested.get("access_token"):
        return nested
    return None


def _authenticated(channel: str, contact: str, session: dict[str, Any], user: Any) -> dict[str, Any]:
    user_id = user.get("id") if isinstance(user, dict) else None
    nested_user = session.get("user")
    if user_id is None and isinstance(nested_user, dict):
        user_id = nested_user.get("id")
    return {
        "status": "authenticated",
        "channel": channel,
        "destination": _mask(channel, contact),
        "verification_type": None,
        "access_token": session.get("access_token"),
        "refresh_token": session.get("refresh_token"),
        "user_id": user_id,
    }


def _pending(channel: str, contact: str, verification_type: str) -> dict[str, Any]:
    return {
        "status": "verification_required",
        "channel": channel,
        "destination": _mask(channel, contact),
        "verification_type": verification_type,
        "access_token": None,
        "refresh_token": None,
        "user_id": None,
    }


def _contact(channel: str, email: Optional[str], phone: Optional[str]) -> str:
    if channel == "email":
        cleaned = (email or "").strip().lower()
        if not EMAIL_RE.match(cleaned):
            raise AuthError("Enter a valid email address.")
        return cleaned
    cleaned = re.sub(r"[\s()-]", "", phone or "")
    if not PHONE_RE.match(cleaned):
        raise AuthError("Enter the phone number with a country code, like +9198xxxxxxx.")
    return cleaned


def _needs_confirmation(message: str) -> bool:
    lowered = message.lower()
    return "not confirmed" in lowered or "email_not_confirmed" in lowered or "phone_not_confirmed" in lowered


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return "Authentication failed."
    if not isinstance(data, dict):
        return "Authentication failed."
    return str(data.get("msg") or data.get("error_description") or data.get("error") or data.get("error_code") or "Authentication failed.")


def _friendly(message: str) -> str:
    lowered = message.lower()
    if "invalid login" in lowered or "invalid_grant" in lowered:
        return "That login doesn't match. Check the details, or create an account."
    if "already registered" in lowered or "already been registered" in lowered:
        return "An account with that contact already exists. Log in instead."
    if "password" in lowered and ("weak" in lowered or "at least" in lowered):
        return "Use a password of at least 8 characters."
    if "phone" in lowered and ("provider" in lowered or "sms" in lowered or "not enabled" in lowered):
        return "Phone codes are not turned on for this project yet. Use email, or enable the phone provider in Supabase."
    if "signups not allowed" in lowered:
        return "New signups are disabled in the Supabase project."
    if "rate" in lowered or "too many" in lowered:
        return "Too many attempts. Wait a minute and try again."
    if len(message) > 180:
        return "Authentication failed."
    return message


def _mask(channel: str, contact: str) -> str:
    if channel == "email" and "@" in contact:
        name, domain = contact.split("@", 1)
        head = name[:1]
        return f"{head}***@{domain}"
    digits = re.sub(r"\D", "", contact)
    if len(digits) >= 4:
        return f"+{digits[:2]} •••• {digits[-4:]}"
    return "your contact"
