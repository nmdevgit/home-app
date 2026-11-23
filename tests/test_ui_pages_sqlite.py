"""Round-2 pages against the real SqliteRepository (in-memory)."""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest


def _script() -> None:
    from datetime import date

    import streamlit as st

    from core.sqlite_repo import SqliteRepository
    from views import archive, bills, dashboard, grocery, meals, notes, settings, tasks

    if "repo" not in st.session_state:
        repo = SqliteRepository(":memory:", "nick")
        repo.add_task("Vacuum", "nick", date.today(), "weekly", priority="high", rotate=True)
        repo.add_grocery("Milk", "2", "dairy")
        meal = repo.add_meal(date.today(), "Pasta", "pasta\nsauce")
        repo.meal_to_grocery(meal.id)
        repo.add_bill("Rent", 150000, date.today(), "monthly")
        repo.add_note("Wifi", "pw", True)
        st.session_state["repo"] = repo
        st.session_state["me"] = "nick"
    pages = {"archive": archive, "bills": bills, "dashboard": dashboard, "grocery": grocery,
             "meals": meals, "notes": notes, "settings": settings, "tasks": tasks}
    pages[st.session_state["page"]].render()


@pytest.mark.parametrize(
    "page", ["archive", "bills", "dashboard", "grocery", "meals", "notes", "settings", "tasks"]
)
def test_page_renders_on_sqlite(page: str) -> None:
    at = AppTest.from_function(_script, default_timeout=20)
    at.session_state["page"] = page
    at.run()
    assert not at.exception
    assert not at.error
