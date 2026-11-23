"""Missing config must fail closed: no dev mode, no login form, no data access."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui import state

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_missing_secrets_does_not_enable_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME_APP_DEV", raising=False)
    monkeypatch.setattr(state, "secret", lambda name: "")
    at = AppTest.from_file(APP, default_timeout=20).run()
    assert not at.exception
    assert any("not configured" in e.value for e in at.error)
    assert not any("DEV MODE" in w.value for w in at.warning)
    assert len(at.button) == 0  # no login / continue button rendered
