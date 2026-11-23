"""AppTest smoke tests in dev mode (local SQLite in a temp file)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui import state

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def dev_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("HOME_APP_DEV", "1")
    monkeypatch.setattr(state, "DEV_DB_PATH", tmp_path / "t.db")
    return AppTest.from_file(APP, default_timeout=20).run()


def test_login_page_shows_dev_banner(dev_app: AppTest) -> None:
    assert not dev_app.exception
    assert any("DEV MODE" in w.value for w in dev_app.warning)
    assert dev_app.button[0].label == "Continue"


def test_login_then_add_grocery(dev_app: AppTest) -> None:
    dev_app.button[0].click().run()
    assert not dev_app.exception
    assert any("Good" in m.value for m in dev_app.markdown)


def _page_script() -> None:
    import streamlit as st

    from core.sqlite_repo import SqliteRepository
    from views import dashboard, grocery, tasks

    if "repo" not in st.session_state:
        repo = SqliteRepository(":memory:", "nick")
        repo.add_task("Take out trash", "nick", None)
        repo.add_grocery("Milk", "2")
        st.session_state["repo"] = repo
        st.session_state["me"] = "nick"
    pages = {"dashboard": dashboard, "grocery": grocery, "tasks": tasks}
    pages[st.session_state.get("page", "tasks")].render()


@pytest.mark.parametrize("page", ["dashboard", "tasks", "grocery"])
def test_pages_render(page: str) -> None:
    at = AppTest.from_function(_page_script, default_timeout=20)
    at.session_state["page"] = page
    at.run()
    assert not at.exception


def test_grocery_add_and_check() -> None:
    at = AppTest.from_function(_page_script, default_timeout=20)
    at.session_state["page"] = "grocery"
    at.run()
    at.text_input(key="g_name").set_value("Eggs")
    at.button[0].click().run()
    assert not at.exception
    labels = [c.label for c in at.checkbox]
    assert "Eggs" in labels and "Milk (2)" in labels
