from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from core import auth
from core.errors import AuthError


class FakeAuth:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.session: SimpleNamespace | None = SimpleNamespace(expires_at=time.time() + 3600)
        self.signed_out = False

    def _resp(self) -> SimpleNamespace:
        user = SimpleNamespace(id="u1", email="n@example.com")
        session = SimpleNamespace(access_token="acc", refresh_token="ref", user=user)
        return SimpleNamespace(user=user, session=session)

    def sign_in_with_password(self, creds: dict[str, str]) -> SimpleNamespace:
        if self.fail:
            raise RuntimeError("bad credentials for secret-user")
        return self._resp()

    def set_session(self, access: str, refresh: str) -> SimpleNamespace:
        if self.fail:
            raise RuntimeError("expired")
        return self._resp()

    def get_session(self) -> SimpleNamespace | None:
        return self.session

    def refresh_session(self) -> SimpleNamespace:
        return self._resp()

    def sign_out(self, options: dict[str, str] | None = None) -> None:
        if self.fail:
            raise RuntimeError("offline")
        self.signed_out = True


class FakeClient:
    def __init__(self, fail: bool = False) -> None:
        self.auth = FakeAuth(fail)
        self.postgrest = SimpleNamespace(auth=self._set_token)
        self.token: str | None = None

    def _set_token(self, token: str) -> None:
        self.token = token


def _patch(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(auth, "make_client", lambda url, key: client)


def test_sign_in_sets_jwt_on_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    _patch(monkeypatch, fake)
    client, info = auth.sign_in("u", "k", " n@example.com ", "pw")
    assert client is fake and fake.token == "acc"
    assert (info.user_id, info.refresh_token) == ("u1", "ref")


def test_sign_in_failure_is_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeClient(fail=True))
    with pytest.raises(AuthError) as exc:
        auth.sign_in("u", "k", "n@example.com", "pw")
    assert "secret-user" not in str(exc.value)


def test_sign_in_requires_credentials() -> None:
    with pytest.raises(AuthError):
        auth.sign_in("u", "k", "", "pw")
    with pytest.raises(AuthError):
        auth.make_client("", "k")


def test_restore_and_sign_out(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    _patch(monkeypatch, fake)
    _, info = auth.restore_session("u", "k", "acc", "ref")
    assert info.access_token == "acc" and fake.token == "acc"
    auth.sign_out(fake)
    assert fake.auth.signed_out
    with pytest.raises(AuthError):
        auth.restore_session("u", "k", "", "")


def test_restore_failure_and_sign_out_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failing: Any = FakeClient(fail=True)
    _patch(monkeypatch, failing)
    with pytest.raises(AuthError):
        auth.restore_session("u", "k", "a", "r")
    auth.sign_out(failing)  # must not raise


def test_refresh_only_when_near_expiry() -> None:
    fake = FakeClient()
    assert auth.refresh(fake) is None  # an hour left
    fake.auth.session = SimpleNamespace(expires_at=time.time() + 10)
    info = auth.refresh(fake)
    assert info is not None and fake.token == "acc"


def test_refresh_without_session_raises() -> None:
    fake = FakeClient()
    fake.auth.session = None
    with pytest.raises(AuthError):
        auth.refresh(fake)


def test_real_supabase_client_offline() -> None:
    """Exercise the installed supabase-py (no network): option names + JWT header."""
    client = auth.make_client("https://example.supabase.co", "sb_publishable_dummy")
    assert client.options.auto_refresh_token is False
    assert client.options.persist_session is False
    auth._attach_jwt(client, "user.jwt.token")
    assert client.postgrest.headers["Authorization"] == "Bearer user.jwt.token"
    assert callable(client.auth.set_session) and callable(client.auth.refresh_session)
