"""Session, mode (dev vs cloud) and repository access. Per-session state only."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from core.repo import Repository
from ui.grouping import PEOPLE

DEV_DB_PATH = Path(__file__).resolve().parent.parent / "dev_home.db"


def secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:
        return ""


def _supabase_key() -> str:
    """Publishable key (SUPABASE_KEY); legacy name SUPABASE_ANON_KEY still accepted."""
    return secret("SUPABASE_KEY") or secret("SUPABASE_ANON_KEY")


def dev_mode() -> bool:
    """Dev mode ONLY on explicit opt-in (HOME_APP_DEV=1). Never inferred from missing
    secrets: a misconfigured public deployment must fail closed, not skip login."""
    return os.environ.get("HOME_APP_DEV") == "1"


def cloud_configured() -> bool:
    """All secrets needed for real logins are present."""
    return all(
        (secret("SUPABASE_URL"), _supabase_key(), secret("NICK_EMAIL"), secret("NATALIE_EMAIL"))
    )


def person_for_email(email: str) -> str | None:
    """Map a login email to 'nick' / 'natalie' using ONLY NICK_EMAIL / NATALIE_EMAIL secrets."""
    mail = email.strip().lower()
    for person in PEOPLE:
        configured = secret(f"{person.upper()}_EMAIL").strip().lower()
        if configured and mail == configured:
            return person
    return None


def current_user() -> str | None:
    """The logged-in person key ('nick'/'natalie') or None."""
    return st.session_state.get("me")


def current_repo() -> Repository | None:
    """Repository bound to the logged-in user (None if logged out)."""
    return st.session_state.get("repo")


def start_dev_session(person: str) -> None:
    from core.sqlite_repo import SqliteRepository

    st.session_state["repo"] = SqliteRepository(str(DEV_DB_PATH), person)
    st.session_state["me"] = person


def start_cloud_session(email: str, password: str) -> None:
    """Sign in with Supabase. Raises core.errors.AuthError on failure."""
    from core import auth
    from core.errors import AuthError
    from core.supabase_repo import SupabaseRepository

    client, info = auth.sign_in(
        secret("SUPABASE_URL"), _supabase_key(), email, password
    )
    person = person_for_email(info.email or email)
    if person is None:
        auth.sign_out(client)
        raise AuthError("This account is not set up as Nick or Natalie in this app.")
    st.session_state["client"] = client
    st.session_state["repo"] = SupabaseRepository(client, info.user_id)
    st.session_state["me"] = person


def refresh_session() -> None:
    """Refresh the JWT at the top of each run (client has auto-refresh off).

    On failure the user is signed out locally and asked to log in again.
    """
    client = st.session_state.get("client")
    if client is None:
        return
    try:
        client.auth.refresh_session()
    except Exception:
        _clear()
        st.session_state["_flash"] = [("error", "Your session expired. Please sign in again.")]


def sign_out() -> None:
    client = st.session_state.get("client")
    if client is not None:
        from core import auth

        auth.sign_out(client)  # never raises; failures are logged by core.auth
    _clear()


def _clear() -> None:
    for key in ("repo", "me", "client"):
        st.session_state.pop(key, None)
