"""Thin helpers around Supabase Auth.

The anon key is public by design; safety comes from RLS, which only applies
when requests carry the signed-in user's JWT. These helpers produce a client
that does. Tokens are returned to the caller (the UI decides where to store
them, e.g. st.session_state); nothing is written to disk here.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from core.errors import AuthError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionInfo:
    user_id: str
    email: str
    access_token: str
    refresh_token: str


def make_client(url: str, anon_key: str) -> Any:
    """Create an anonymous client. Session persistence is off: Streamlit
    servers are shared processes, so tokens must never live in module state
    or files."""
    if not url or not anon_key:
        raise AuthError("Supabase url and anon key are required")
    # Imported lazily so the SQLite/dev path works without supabase installed.
    from supabase import ClientOptions, create_client

    options = ClientOptions(auto_refresh_token=False, persist_session=False)
    return create_client(url, anon_key, options=options)


def _to_info(session: Any, user: Any = None) -> SessionInfo:
    # Some responses carry the user only on the session, others only on the response.
    user = user or getattr(session, "user", None)
    if session is None or user is None:
        raise AuthError("no session returned")
    return SessionInfo(
        user_id=str(user.id),
        email=str(user.email or ""),
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )


def _attach_jwt(client: Any, access_token: str) -> None:
    """supabase-py 2.x already swaps the Authorization header on auth events;
    setting it on postgrest explicitly keeps RLS correct even if that changes."""
    client.postgrest.auth(access_token)


def sign_in(url: str, anon_key: str, email: str, password: str) -> tuple[Any, SessionInfo]:
    """Password sign-in. Returns (client carrying the user's JWT, tokens)."""
    if not email.strip() or not password:
        raise AuthError("email and password are required")
    client = make_client(url, anon_key)
    try:
        response = client.auth.sign_in_with_password(
            {"email": email.strip(), "password": password}
        )
    except Exception as exc:  # supabase raises several AuthApiError variants
        # Deliberately generic: do not reveal whether the email exists.
        logger.warning("sign-in failed: %s", type(exc).__name__)
        raise AuthError("sign-in failed; check email and password") from exc
    info = _to_info(response.session, response.user)
    _attach_jwt(client, info.access_token)
    return client, info


def restore_session(
    url: str, anon_key: str, access_token: str, refresh_token: str
) -> tuple[Any, SessionInfo]:
    """Rebuild a client from stored tokens; set_session refreshes if expired.
    The returned SessionInfo may hold NEW tokens, which the caller must store."""
    if not access_token or not refresh_token:
        raise AuthError("no stored session")
    client = make_client(url, anon_key)
    try:
        response = client.auth.set_session(access_token, refresh_token)
    except Exception as exc:
        logger.warning("session restore failed: %s", type(exc).__name__)
        raise AuthError("session expired; please sign in again") from exc
    info = _to_info(response.session, response.user)
    _attach_jwt(client, info.access_token)
    return client, info


def refresh(client: Any, margin_seconds: int = 120) -> SessionInfo | None:
    """Refresh the JWT if it expires within margin_seconds. Returns the new
    tokens when refreshed (caller must store them), else None. Raises AuthError
    if the session is gone so the UI can send the user to the login page.
    Done manually per rerun because auto_refresh_token is off (see make_client)."""
    try:
        session = client.auth.get_session()
        if session is None:
            raise AuthError("not signed in")
        if session.expires_at - time.time() >= margin_seconds:
            return None
        response = client.auth.refresh_session()
    except AuthError:
        raise
    except Exception as exc:
        logger.warning("token refresh failed: %s", type(exc).__name__)
        raise AuthError("session expired; please sign in again") from exc
    info = _to_info(response.session, response.user)
    _attach_jwt(client, info.access_token)
    return info


def sign_out(client: Any) -> None:
    """Revoke this device's session only (scope=local: the default 'global'
    would also log the other person's devices out if they share an account).
    Failures are logged, not raised, so the UI can always clear local state."""
    try:
        client.auth.sign_out({"scope": "local"})
    except Exception as exc:
        logger.warning("sign-out call failed: %s", type(exc).__name__)
