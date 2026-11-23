"""AppTest smoke tests for the round-2 pages, using an in-memory fake repository."""
from __future__ import annotations

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from ui.grouping import bill_status, group_grocery, search_tasks, sort_tasks, week_start
from ui.money import format_cents, parse_cents


def _script() -> None:
    from datetime import date

    import streamlit as st

    from tests.ui_fake import FakeRepo
    from views import archive, bills, dashboard, grocery, meals, notes, settings, tasks

    if "repo" not in st.session_state:
        repo = FakeRepo()
        today = date.today()
        repo.add_task("Vacuum", "nick", today, "weekly", "lounge", "high", True)
        repo.add_task("Water plants", "natalie", None)
        done = repo.add_task("Old chore", "nick")
        repo.complete_task(done.id)
        arch = repo.add_task("Archived thing")
        repo.archive_task(arch.id)
        repo.add_grocery("Milk", "2", "dairy")
        repo.add_meal(today, "Pasta", "pasta\nsauce")
        repo.add_bill("Rent", 150000, today)
        repo.add_note("Wifi", "pw", True)
        st.session_state["repo"] = repo
        st.session_state["me"] = "nick"
    pages = {"archive": archive, "bills": bills, "dashboard": dashboard, "grocery": grocery,
             "meals": meals, "notes": notes, "settings": settings, "tasks": tasks}
    pages[st.session_state["page"]].render()


def _run(page: str) -> AppTest:
    at = AppTest.from_function(_script, default_timeout=20)
    at.session_state["page"] = page
    return at.run()


@pytest.mark.parametrize(
    "page", ["archive", "bills", "dashboard", "grocery", "meals", "notes", "settings", "tasks"]
)
def test_page_renders(page: str) -> None:
    at = _run(page)
    assert not at.exception
    assert not at.error


def test_tasks_priority_marker_and_search() -> None:
    at = _run("tasks")
    assert any("HIGH" in c.label for c in at.checkbox)
    at.text_input(key="t_search").set_value("lounge").run()
    labels = [c.label for c in at.checkbox if c.key and c.key.startswith("tasks_chk_")]
    assert len(labels) == 1 and "Vacuum" in labels[0]


def test_rotate_only_with_recurrence() -> None:
    at = _run("tasks")
    assert not [c for c in at.checkbox if c.key == "ta_rot"]
    at.selectbox(key="ta_rec").select("weekly").run()
    assert [c for c in at.checkbox if c.key == "ta_rot"]


def test_bills_rejects_garbage_amount() -> None:
    at = _run("bills")
    at.text_input(key="b_name").set_value("Power")
    at.text_input(key="b_amt").set_value("-5")
    at.button(key="b_add").click().run()
    assert any("amount" in e.value.lower() for e in at.error)


def test_settings_warns_at_80_percent() -> None:
    at = _run("settings")
    assert any("80%" in w.value for w in at.warning)


def test_archive_restore_task() -> None:
    at = _run("archive")
    keys = [b.key for b in at.button if b.key and b.key.startswith("rt_")]
    assert len(keys) == 1
    at.button(key=keys[0]).click().run()
    assert not at.exception


def test_parse_cents() -> None:
    assert parse_cents("$1,234.5") == 123450
    assert parse_cents("45") == 4500
    for bad in ("-1", "abc", "1.234", "", "1e5", "9999999999"):
        with pytest.raises(ValueError):
            parse_cents(bad)
    assert format_cents(4520) == "$45.20"


def test_grouping_helpers() -> None:
    assert week_start(date(2026, 11, 22)) == date(2026, 11, 16)
    today = date(2026, 11, 23)
    assert bill_status(date(2026, 11, 20), today) == "overdue"
    assert bill_status(date(2026, 11, 25), today) == "soon"
    assert bill_status(date(2026, 12, 25), today) == "later"
    assert bill_status(date(2026, 11, 20), today, date(2026, 11, 21)) == "paid"


def test_task_sort_and_search_pure() -> None:
    from tests.ui_fake import FakeRepo

    repo = FakeRepo()
    d = date(2026, 1, 1)
    low = repo.add_task("b", due_date=d, priority="low")
    high = repo.add_task("c", due_date=d, priority="high", notes="Findme")
    none = repo.add_task("a")
    assert sort_tasks([none, low, high]) == [high, low, none]
    assert search_tasks([none, low, high], "findME") == [high]
    repo.add_grocery("x", category="dairy")
    repo.add_grocery("y", category="produce")
    assert list(group_grocery(repo.list_grocery())) == ["produce", "dairy"]
