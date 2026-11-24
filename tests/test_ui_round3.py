"""AppTest smoke + flow tests for the round-3 pages (fake repo and real SqliteRepository)."""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from core.repo import EXPORT_TABLES
from tests.ui_fake import FakeRepo
from ui import theme
from ui.export import build_export_zip, rows_to_csv

PAGES = ["activity", "events", "goals", "search", "agenda", "archive", "bills", "dashboard",
         "expenses", "grocery", "meals", "more", "notes", "settings", "stats", "tasks",
         "templates"]


def _script() -> None:
    from datetime import date

    import streamlit as st

    from core.sqlite_repo import SqliteRepository
    from tests.ui_fake import FakeRepo
    from views import (
        activity,
        agenda,
        archive,
        bills,
        dashboard,
        events,
        expenses,
        goals,
        grocery,
        meals,
        more,
        notes,
        search,
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
        repo.add_event("Anniversary", today, "both")
        repo.add_goal("Holiday", 300000)
        repo.add_template("shopping", "Weekly", "eggs\nbread")
        repo.add_template("recipe", "Tacos", "mince\nshells")
        st.session_state["repo"] = repo
        st.session_state["me"] = "nick"
    pages = {"agenda": agenda, "archive": archive, "bills": bills, "dashboard": dashboard,
             "expenses": expenses, "grocery": grocery, "meals": meals,
             "more": more, "search": search, "events": events, "goals": goals,
             "activity": activity, "notes": notes,
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


def test_grocery_cart_total_and_price_save() -> None:
    at = _run("grocery")
    repo = at.session_state["repo"]
    assert not any("In cart" in m.value for m in at.markdown)
    milk = next(iter(repo.grocery.values()))
    at.checkbox(key=f"g_chk_{milk.id}").check().run()
    assert any("In cart: 1 item" in m.value and "1 without price" in m.value
               for m in at.markdown)
    at.text_input(key=f"g_price_{milk.id}").set_value("$3.50").run()
    assert repo.grocery[milk.id].price_cents == 350
    assert any("$3.50" in m.value and "In cart" in m.value for m in at.markdown)
    at.text_input(key=f"g_price_{milk.id}").set_value("").run()
    assert repo.grocery[milk.id].price_cents is None


def test_grocery_duplicate_add_allowed() -> None:
    at = _run("grocery")
    at.text_input(key="g_name").set_value("milk")
    at.button[0].click().run()
    assert not at.exception
    names = [g.name.lower() for g in at.session_state["repo"].grocery.values()]
    assert names.count("milk") == 2


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
    assert "tasks.csv" in names and "templates.csv" in names and len(names) == len(EXPORT_TABLES)
    assert "'=SUM(A1)" in notes
    assert rows_to_csv([]).strip() == ""


def test_theme_escapes_html() -> None:
    assert "<script>" not in theme.badge("<script>alert(1)</script>")
    assert "&lt;b&gt;" in theme.badge("<b>")
    assert theme.due_badge(date(2026, 1, 1), date(2026, 1, 3)).count("Overdue 2d") == 1
    assert theme.person_badge("zzz").count("Either") == 1


def test_delete_note_forever() -> None:
    at = _run("notes")
    repo: FakeRepo = at.session_state["repo"]
    note_id = next(iter(repo.notes))
    at.button(key=f"del_note_{note_id}_yes").click().run()
    assert not at.exception and note_id not in repo.notes


def test_delete_task_removes_subtasks() -> None:
    at = _run("tasks")
    repo: FakeRepo = at.session_state["repo"]
    task = next(t for t in repo.tasks.values() if t.title == "Vacuum")
    assert any(s.task_id == task.id for s in repo.subtasks.values())
    at.button(key=f"del_task_{task.id}_yes").click().run()
    assert task.id not in repo.tasks and not repo.subtasks


def test_delete_checked_grocery_and_purge_archive() -> None:
    at = _run("grocery")
    repo: FakeRepo = at.session_state["repo"]
    item = next(iter(repo.grocery.values()))
    at.checkbox(key=f"g_chk_{item.id}").check().run()
    at.button(key="del_gro_checked_yes").click().run()
    assert not repo.grocery
    task = next(iter(repo.tasks.values()))
    repo.archive_task(task.id)
    at = _run("archive")
    at.session_state["repo"] = repo
    at.run()
    at.button(key="del_purge_yes").click().run()
    assert not repo.archived_tasks and not at.exception


def test_goal_chip_adds_contribution() -> None:
    at = _run("goals")
    repo: FakeRepo = at.session_state["repo"]
    goal = next(iter(repo.goals.values()))
    at.button(key=f"go_{goal.id}_5000").click().run()
    assert not at.exception and repo.goals[goal.id].saved_cents == 5000


def test_search_page_finds_task() -> None:
    at = _run("search")
    at.text_input(key="s_q").set_value("vacuum").run()
    assert not at.exception
    assert any("Vacuum" in m.value for m in at.markdown)


def test_bulk_done_and_undo_bar() -> None:
    at = _run("tasks")
    repo: FakeRepo = at.session_state["repo"]
    at.toggle(key="t_select").set_value(True).run()
    task = next(t for t in repo.tasks.values() if t.title == "Vacuum")
    at.checkbox(key=f"sel_{task.id}").check().run()
    at.button(key="bk_arch").click().run()
    assert not at.exception and task.id not in repo.tasks


def test_complete_shows_undo_then_reopens() -> None:
    at = _run("tasks")
    repo: FakeRepo = at.session_state["repo"]
    task = next(t for t in repo.tasks.values() if t.title == "Late one")
    at.checkbox(key=f"tasks_chk_{task.id}").check().run()
    assert repo.tasks[task.id].status == "done"
    at.button(key="undo_btn").click().run()
    assert repo.tasks[task.id].status == "open" and not at.exception


def test_settings_look_saves_prefs() -> None:
    at = _run("settings")
    at.toggle(key="lk_compact").set_value(True).run()
    at.button(key="lk_save").click().run()
    repo: FakeRepo = at.session_state["repo"]
    assert not at.exception and repo.prefs.compact is True


def test_signed_out_nav_includes_new_paths() -> None:
    from ui import nav
    assert {"calendar", "goals", "search", "activity"} <= set(nav.url_paths())


def test_bulk_archive_then_undo_restores() -> None:
    at = _run("tasks")
    repo: FakeRepo = at.session_state["repo"]
    at.toggle(key="t_select").set_value(True).run()
    task = next(t for t in repo.tasks.values() if t.title == "Vacuum")
    at.checkbox(key=f"sel_{task.id}").check().run()
    at.button(key="bk_arch").click().run()
    at.button(key="undo_btn").click().run()
    assert task.id in repo.tasks and not at.exception


def test_tasks_page_archived_section_restores() -> None:
    at = _run("tasks")
    repo: FakeRepo = at.session_state["repo"]
    task = next(t for t in repo.tasks.values() if t.title == "Vacuum")
    repo.archive_task(task.id)
    at.run()
    assert any("Archived (1)" in e.label for e in at.expander)
    at.button(key=f"tr_{task.id}").click().run()
    assert task.id in repo.tasks and not at.exception


def test_archive_meal_undo_and_everything_else_tab() -> None:
    at = _run("meals")
    repo: FakeRepo = at.session_state["repo"]
    meal = next(iter(repo.meals.values()))
    repo.update_meal(meal.id, day=date(2025, 1, 1))  # conftest pins today to 2025-01-01
    at.run()
    at.button(key=f"me_{meal.id}_a").click().run()
    assert meal.id not in repo.meals
    at.button(key="undo_btn").click().run()
    assert meal.id in repo.meals and not at.exception
    repo.archive_meal(meal.id)
    at.session_state["page"] = "archive"
    at.run()
    at.button(key=f"ro_meal_{meal.id}").click().run()
    assert meal.id in repo.meals and not at.exception


def test_archive_checked_grocery_undo() -> None:
    at = _run("grocery")
    repo: FakeRepo = at.session_state["repo"]
    milk = next(iter(repo.grocery.values()))
    at.checkbox(key=f"g_chk_{milk.id}").check().run()
    btn = next(b for b in at.button if b.label == "Archive checked")
    btn.click().run()
    assert milk.id not in repo.grocery
    at.button(key="undo_btn").click().run()
    assert milk.id in repo.grocery and not at.exception


def test_every_archived_kind_has_restore_and_delete() -> None:
    from typing import get_args

    from core.repo import ArchivedKind
    from views import archive
    repo = FakeRepo()
    for kind in get_args(ArchivedKind):
        assert callable(archive._delete_fn(repo, kind)), kind
        assert kind in archive._KINDS, kind
    assert callable(repo.restore_item)
