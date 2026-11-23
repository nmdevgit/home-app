"""AppTest smoke + flow tests for the round-3 pages (fake repo and real SqliteRepository)."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from tests.ui_fake import FakeRepo
from ui import theme
from ui.export import build_export_zip, rows_to_csv

PAGES = ["agenda", "archive", "bills", "dashboard", "expenses", "grocery", "meals", "notes",
         "settings", "stats", "tasks", "templates"]


def _script() -> None:
    from datetime import date

    import streamlit as st

    from core.sqlite_repo import SqliteRepository
    from tests.ui_fake import FakeRepo
    from views import (
        agenda,
        archive,
        bills,
        dashboard,
        expenses,
        grocery,
        meals,
        notes,
        settings,
        stats,
        tasks,
        templates,
    )

    if "repo" not in st.session_state:
        repo = FakeRepo() if st.session_state["backend"] == "fake" else SqliteRepository(
            ":memory:", "nick")
        today = date.today()
        task = repo.add_task("Vacuum", "nick", today, "weekly", "lounge", "high", True)
        repo.add_task("Late one", "natalie", date(2020, 1, 1))
        repo.add_subtask(task.id, "Lounge")
        repo.complete_task(repo.add_task("Done one", "nick").id)
        repo.add_grocery("Milk", "2", "dairy")
        repo.add_meal(today, "Pasta", "pasta\nsauce")
        repo.add_bill("Rent", 150000, today)
        repo.add_note("Wifi", "pw", True)
        repo.add_expense(today, "Dinner", 5000, "nick")
        repo.add_template("shopping", "Weekly", "eggs\nbread")
        repo.add_template("recipe", "Tacos", "mince\nshells")
        st.session_state["repo"] = repo
        st.session_state["me"] = "nick"
    pages = {"agenda": agenda, "archive": archive, "bills": bills, "dashboard": dashboard,
             "expenses": expenses, "grocery": grocery, "meals": meals, "notes": notes,
             "settings": settings, "stats": stats, "tasks": tasks, "templates": templates}
    pages[st.session_state["page"]].render()


def _run(page: str, backend: str = "fake") -> AppTest:
    at = AppTest.from_function(_script, default_timeout=20)
    at.session_state["page"] = page
    at.session_state["backend"] = backend
    return at.run()


@pytest.mark.parametrize("backend", ["fake", "sqlite"])
@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page: str, backend: str) -> None:
    at = _run(page, backend)
    assert not at.exception
    assert not at.error


def test_quick_add_preview_then_confirm() -> None:
    at = _run("tasks")
    at.text_input(key="tq_text").set_value("Buy bread tomorrow for natalie !high every week")
    at.button[0].click().run()
    assert any("understood" in c.value for c in at.caption)
    at.button(key="tq_ok").click().run()
    assert not at.exception
    repo: FakeRepo = at.session_state["repo"]
    added = [t for t in repo.tasks.values() if "bread" in t.title.lower()]
    assert added and added[0].assignee == "natalie" and added[0].priority == "high"


def test_quick_add_cancel_adds_nothing() -> None:
    at = _run("tasks")
    before = len(at.session_state["repo"].tasks)
    at.text_input(key="tq_text").set_value("Water plants")
    at.button[0].click().run()
    at.button(key="tq_cancel").click().run()
    assert len(at.session_state["repo"].tasks) == before


def test_task_groups_and_subtask_progress() -> None:
    at = _run("tasks")
    headings = " ".join(m.value for m in at.markdown)
    assert "Overdue" in headings and "Later" in headings
    assert "0/1 steps" in headings


def test_grocery_quick_add_parses() -> None:
    at = _run("grocery")
    at.text_input(key="g_name").set_value("2 eggs")
    at.button[0].click().run()
    assert not at.exception
    names = [g.name.lower() for g in at.session_state["repo"].grocery.values()]
    assert any("egg" in n for n in names)


def test_grocery_saved_list_adds_items() -> None:
    at = _run("grocery")
    at.button(key="g_tpl_add").click().run()
    names = {g.name for g in at.session_state["repo"].grocery.values()}
    assert {"eggs", "bread"} <= names


def test_expenses_balance_and_settle() -> None:
    at = _run("expenses")
    assert any("Natalie owes Nick" in m.value for m in at.markdown)
    at.button(key="x_settle").click().run()
    assert not at.exception
    kinds = [e.kind for e in at.session_state["repo"].expenses.values()]
    assert "settlement" in kinds
    assert any("All square" in m.value for m in at.markdown)


def test_expense_rejects_bad_amount() -> None:
    at = _run("expenses")
    at.text_input(key="x_desc").set_value("Lunch")
    at.text_input(key="x_amt").set_value("abc")
    at.button(key="x_add").click().run()
    assert any("amount" in e.value.lower() for e in at.error)


def test_template_plan_recipe_adds_meal() -> None:
    at = _run("templates")
    at.segmented_control(key="tp_kind").set_value("recipe").run()
    plan = [b for b in at.button if b.key and b.key.endswith("_plan")]
    assert plan
    plan[0].click().run()
    titles = [m.title for m in at.session_state["repo"].meals.values()]
    assert "Tacos" in titles


def test_agenda_next_week_navigates() -> None:
    at = _run("agenda")
    first = at.session_state["ag_week"]
    at.button(key="ag_next").click().run()
    assert (at.session_state["ag_week"] - first).days == 7


def test_settings_download_prepared() -> None:
    at = _run("settings")
    at.button(key="export_prepare").click().run()
    assert not at.exception
    assert zipfile.is_zipfile(io.BytesIO(at.session_state["export_zip"]))


def test_export_zip_has_all_tables_and_neutralises_formulas() -> None:
    repo = FakeRepo()
    with zipfile.ZipFile(io.BytesIO(build_export_zip(repo))) as zf:
        names = set(zf.namelist())
        notes = zf.read("notes.csv").decode()
    assert "tasks.csv" in names and "templates.csv" in names and len(names) == 8
    assert "'=SUM(A1)" in notes
    assert rows_to_csv([]).strip() == ""


def test_theme_escapes_html() -> None:
    assert "<script>" not in theme.badge("<script>alert(1)</script>")
    assert "&lt;b&gt;" in theme.badge("<b>")
    assert theme.due_badge(date(2026, 1, 1), date(2026, 1, 3)).count("Overdue 2d") == 1
    assert theme.person_badge("zzz").count("Either") == 1
