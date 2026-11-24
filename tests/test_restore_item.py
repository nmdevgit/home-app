"""list_archived_items / restore_item on both repositories."""
from __future__ import annotations

import time as time_mod
from datetime import date, time

import pytest

from core.errors import NotFoundError, ValidationError
from core.sqlite_repo import SqliteRepository
from core.supabase_repo import SupabaseRepository
from tests.test_supabase_repo import FakeClient


@pytest.fixture(params=["sqlite", "supabase"])
def repo(request: pytest.FixtureRequest, tmp_path):  # type: ignore[no-untyped-def]
    if request.param == "sqlite":
        return SqliteRepository(str(tmp_path / "t.db"), "nick-id")
    return SupabaseRepository(FakeClient(), "nick-id")


def _archive_all(repo):  # type: ignore[no-untyped-def]
    d = date(2026, 3, 4)
    ids = {}
    ids["meal"] = repo.add_meal(d, "Pasta").id
    repo.archive_meal(ids["meal"])
    ids["bill"] = repo.add_bill("Power", 12345, d).id
    repo.archive_bill(ids["bill"])
    ids["note"] = repo.add_note("Wifi", "pw").id
    repo.archive_note(ids["note"])
    ids["expense"] = repo.add_expense(d, "Pizza", 2050, "nick").id
    repo.archive_expense(ids["expense"])
    ids["template"] = repo.add_template("shopping", "Weekly", "milk").id
    repo.archive_template(ids["template"])
    ids["event"] = repo.add_event("Party", d, start_time=time(18, 0)).id
    repo.archive_event(ids["event"])
    ids["goal"] = repo.add_goal("Holiday", 500000).id
    repo.archive_goal(ids["goal"])
    task = repo.add_task("T")
    ids["subtask"] = repo.add_subtask(task.id, "step").id
    repo.archive_subtask(ids["subtask"])
    return ids


def test_list_and_restore_every_kind(repo) -> None:  # type: ignore[no-untyped-def]
    ids = _archive_all(repo)
    items = repo.list_archived_items()
    assert {i.kind for i in items} == set(ids)
    by = {i.kind: i for i in items}
    assert by["bill"].title == "Power" and "$123.45" in by["bill"].detail
    assert "2026-03-04" in by["bill"].detail
    assert "$20.50" in by["expense"].detail
    assert "$5,000.00" in by["goal"].detail
    assert by["event"].detail == "2026-03-04"
    assert by["subtask"].title == "step"
    assert all(i.archived_at.tzinfo is not None for i in items)
    for kind, rid in ids.items():
        repo.restore_item(kind, rid)
    assert repo.list_archived_items() == []
    assert [g.name for g in repo.list_goals()] == ["Holiday"]
    assert [m.title for m in repo.list_meals(date(2026, 3, 1), date(2026, 3, 31))] == ["Pasta"]
    assert len(repo.list_bills()) == 1 and len(repo.list_notes()) == 1
    assert len(repo.list_expenses()) == 1 and len(repo.list_templates()) == 1
    assert len(repo.list_events(date(2026, 3, 1), date(2026, 3, 31))) == 1
    task_id = repo.list_tasks()[0].id
    assert [s.title for s in repo.list_subtasks([task_id])] == ["step"]


def test_restore_errors(repo) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        repo.restore_item("task", "x")
    with pytest.raises(NotFoundError):
        repo.restore_item("goal", "missing")
    with pytest.raises(NotFoundError):
        repo.restore_item("subtask", "missing")
    g = repo.add_goal("Active", 1000)
    with pytest.raises(NotFoundError):  # not archived
        repo.restore_item("goal", g.id)


def test_subtask_with_archived_or_deleted_task(repo) -> None:  # type: ignore[no-untyped-def]
    t = repo.add_task("parent")
    s = repo.add_subtask(t.id, "child")
    repo.archive_subtask(s.id)
    repo.archive_task(t.id)
    with pytest.raises(ValidationError, match="restore the task first"):
        repo.restore_item("subtask", s.id)
    repo.restore_task(t.id)
    repo.restore_item("subtask", s.id)
    repo.archive_subtask(s.id)
    repo.delete_task(t.id)
    with pytest.raises((ValidationError, NotFoundError)):
        repo.restore_item("subtask", s.id)


def test_newest_archived_first(repo) -> None:  # type: ignore[no-untyped-def]
    a = repo.add_note("first")
    b = repo.add_note("second")
    repo.archive_note(a.id)
    time_mod.sleep(0.05)
    repo.archive_note(b.id)
    assert [i.title for i in repo.list_archived_items()] == ["second", "first"]
