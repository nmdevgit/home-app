from __future__ import annotations

from datetime import UTC, date

import pytest

from core.errors import NotFoundError, ValidationError
from core.sqlite_repo import SqliteRepository


def _count(repo: SqliteRepository, table: str) -> int:
    return repo._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_add_and_list_task(repo: SqliteRepository) -> None:
    task = repo.add_task("  Take out bins ", assignee="natalie", due_date=date(2025, 1, 2))
    assert task.title == "Take out bins"
    assert task.status == "open"
    assert task.created_by == "nick-id"
    assert task.created_at.tzinfo is not None
    assert task.created_at.utcoffset() == UTC.utcoffset(None)
    assert repo.list_tasks() == [task]


def test_list_orders_dated_first(repo: SqliteRepository) -> None:
    undated = repo.add_task("undated")
    late = repo.add_task("late", due_date=date(2025, 5, 1))
    early = repo.add_task("early", due_date=date(2025, 1, 1))
    assert [t.id for t in repo.list_tasks()] == [early.id, late.id, undated.id]


def test_complete_and_reopen(repo: SqliteRepository) -> None:
    task = repo.add_task("one-off")
    done = repo.complete_task(task.id)
    assert done.status == "done" and done.completed_at is not None
    assert repo.list_tasks() == []
    assert [t.id for t in repo.list_tasks(include_done=True)] == [task.id]
    assert repo.complete_task(task.id) == done  # idempotent, no duplicates
    assert _count(repo, "tasks") == 1
    reopened = repo.reopen_task(task.id)
    assert reopened.status == "open" and reopened.completed_at is None


@pytest.mark.parametrize(
    ("recurrence", "due", "expected"),
    [
        ("daily", date(2025, 3, 1), date(2025, 3, 2)),
        ("weekly", date(2025, 3, 1), date(2025, 3, 8)),
        ("monthly", date(2025, 3, 1), date(2025, 4, 1)),
        ("monthly", date(2025, 1, 31), date(2025, 2, 28)),
    ],
)
def test_recurrence_creates_next_occurrence(
    repo: SqliteRepository, recurrence: str, due: date, expected: date
) -> None:
    task = repo.add_task("chore", assignee="nick", due_date=due, recurrence=recurrence,
                         notes="n")  # type: ignore[arg-type]
    repo.complete_task(task.id)
    (nxt,) = repo.list_tasks()
    assert nxt.id != task.id
    assert nxt.due_date == expected
    copied = (nxt.title, nxt.assignee, nxt.recurrence, nxt.notes)
    assert copied == ("chore", "nick", recurrence, "n")
    assert nxt.status == "open"


def test_recurrence_without_due_date_uses_today(repo: SqliteRepository) -> None:

    task = repo.add_task("chore", recurrence="daily")
    repo.complete_task(task.id)
    (nxt,) = repo.list_tasks()
    assert nxt.due_date is not None
    assert nxt.due_date > date(2025, 1, 1)


def test_update_task(repo: SqliteRepository) -> None:
    task = repo.add_task("a")
    updated = repo.update_task(task.id, title="b", due_date=date(2025, 2, 2), assignee="nick")
    assert (updated.title, updated.due_date, updated.assignee) == ("b", date(2025, 2, 2), "nick")
    assert repo.update_task(task.id, due_date=None).due_date is None


def test_archive_hides_but_keeps_row(repo: SqliteRepository) -> None:
    task = repo.add_task("gone")
    repo.archive_task(task.id)
    assert repo.list_tasks(include_done=True) == []
    assert _count(repo, "tasks") == 1
    archived = repo._conn.execute("SELECT archived_at FROM tasks").fetchone()[0]
    assert archived is not None
    with pytest.raises(NotFoundError):
        repo.complete_task(task.id)
    with pytest.raises(NotFoundError):
        repo.archive_task(task.id)


def test_not_found(repo: SqliteRepository) -> None:
    for call in (repo.complete_task, repo.reopen_task, repo.archive_task):
        with pytest.raises(NotFoundError):
            call("missing")
    with pytest.raises(NotFoundError):
        repo.update_task("missing", title="x")
    with pytest.raises(NotFoundError):
        repo.set_grocery_checked("missing", True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "ok", "notes": "n" * 2001},
        {"title": "ok", "assignee": "bob"},
        {"title": "ok", "recurrence": "yearly"},
        {"title": "ok", "due_date": "2025-01-01"},
    ],
)
def test_add_task_validation(repo: SqliteRepository, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        repo.add_task(**kwargs)  # type: ignore[arg-type]
    assert _count(repo, "tasks") == 0


def test_update_validation(repo: SqliteRepository) -> None:
    task = repo.add_task("a")
    with pytest.raises(ValidationError):
        repo.update_task(task.id, title="")
    with pytest.raises(ValidationError):
        repo.update_task(task.id, status="done")  # not updatable directly
    with pytest.raises(ValidationError):
        repo.update_task(task.id, **{"title = 'x' --": "y"})


def test_max_lengths_accepted(repo: SqliteRepository) -> None:
    repo.add_task("x" * 200, notes="n" * 2000)


def test_grocery_flow(repo: SqliteRepository) -> None:
    milk = repo.add_grocery(" Milk ", "2L")
    eggs = repo.add_grocery("Eggs")
    assert milk.name == "Milk" and milk.added_by == "nick-id" and not milk.checked
    assert repo.set_grocery_checked(milk.id, True).checked is True
    assert [i.id for i in repo.list_grocery()] == [eggs.id, milk.id]  # unchecked first
    assert repo.archive_checked_grocery() == 1
    assert [i.id for i in repo.list_grocery()] == [eggs.id]
    assert _count(repo, "grocery_items") == 2
    assert repo.archive_checked_grocery() == 0


@pytest.mark.parametrize(
    ("name", "qty"), [("", ""), ("  ", ""), ("x" * 201, ""), ("ok", "q" * 101)]
)
def test_grocery_validation(repo: SqliteRepository, name: str, qty: str) -> None:
    with pytest.raises(ValidationError):
        repo.add_grocery(name, qty)


def test_persists_on_disk(tmp_path) -> None:
    path = tmp_path / "app.db"
    first = SqliteRepository(path, "u1")
    first.add_task("persist")
    second = SqliteRepository(path, "u2")
    assert [t.title for t in second.list_tasks()] == ["persist"]


def test_overdue_recurring_rolls_forward(repo: SqliteRepository, fixed_today: date) -> None:
    task = repo.add_task("old", due_date=date(2024, 12, 1), recurrence="weekly")
    repo.complete_task(task.id)
    (nxt,) = repo.list_tasks()
    assert nxt.due_date == date(2025, 1, 5)  # Dec 1 + 5 weeks, first >= Jan 1
