"""Permanent delete methods (SqliteRepository)."""
from __future__ import annotations

from datetime import date

import pytest

from core.errors import NotFoundError
from core.sqlite_repo import SqliteRepository


@pytest.fixture()
def repo() -> SqliteRepository:
    return SqliteRepository(":memory:", user_id="u")


def _count(repo: SqliteRepository, table: str) -> int:
    return repo._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_delete_task_removes_subtasks_even_archived(repo: SqliteRepository) -> None:
    keep, gone = repo.add_task("keep"), repo.add_task("gone")
    repo.add_subtask(keep.id, "k")
    s = repo.add_subtask(gone.id, "a")
    repo.add_subtask(gone.id, "b")
    repo.archive_subtask(s.id)
    repo.delete_task(gone.id)
    assert [t.id for t in repo.list_tasks()] == [keep.id]
    assert _count(repo, "subtasks") == 1
    with pytest.raises(NotFoundError):
        repo.delete_task(gone.id)


def test_delete_archived_rows_and_not_found(repo: SqliteRepository) -> None:
    task = repo.add_task("t")
    repo.archive_task(task.id)
    repo.delete_task(task.id)
    assert _count(repo, "tasks") == 0
    deleters = [
        repo.delete_subtask, repo.delete_grocery, repo.delete_meal, repo.delete_bill,
        repo.delete_note, repo.delete_expense, repo.delete_template,
    ]
    for fn in deleters:
        with pytest.raises(NotFoundError):
            fn("missing")


def test_each_delete(repo: SqliteRepository) -> None:
    t = repo.add_task("t")
    sub = repo.add_subtask(t.id, "s")
    g = repo.add_grocery("g")
    m = repo.add_meal(date(2025, 1, 1), "m")
    b = repo.add_bill("b", 100, date(2025, 1, 1))
    n = repo.add_note("n")
    e = repo.add_expense(date(2025, 1, 1), "e", 100, "nick")
    tpl = repo.add_template("shopping", "x", "i")
    repo.archive_note(n.id)  # archived rows delete too
    repo.delete_subtask(sub.id)
    repo.delete_grocery(g.id)
    repo.delete_meal(m.id)
    repo.delete_bill(b.id)
    repo.delete_note(n.id)
    repo.delete_expense(e.id)
    repo.delete_template(tpl.id)
    for table in ("subtasks", "grocery_items", "meals", "bills", "notes", "expenses", "templates"):
        assert _count(repo, table) == 0
    assert _count(repo, "tasks") == 1


def test_delete_checked_grocery(repo: SqliteRepository) -> None:
    a, b, c = (repo.add_grocery(x) for x in "abc")
    repo.set_grocery_checked(a.id, True)
    repo.set_grocery_checked(b.id, True)
    repo.archive_checked_grocery()  # a, b archived: must survive
    d = repo.add_grocery("d")
    repo.set_grocery_checked(d.id, True)
    assert repo.delete_checked_grocery() == 1
    assert [g.name for g in repo.list_grocery()] == ["c"]
    assert len(repo.list_archived_grocery()) == 2
    assert c.id and repo.delete_checked_grocery() == 0


def test_purge_archived(repo: SqliteRepository) -> None:
    live = repo.add_task("live")
    dead = repo.add_task("dead")
    repo.add_subtask(live.id, "keep")
    repo.add_subtask(dead.id, "child")  # not archived itself, parent is
    arch_sub = repo.add_subtask(live.id, "arch")
    repo.archive_subtask(arch_sub.id)
    repo.archive_task(dead.id)
    g = repo.add_grocery("g")
    repo.archive_checked_grocery()
    repo.set_grocery_checked(g.id, True)
    repo.archive_checked_grocery()
    m = repo.add_meal(date(2025, 1, 1), "m")
    repo.archive_meal(m.id)
    repo.archive_bill(repo.add_bill("b", 1, date(2025, 1, 1)).id)
    repo.archive_note(repo.add_note("n").id)
    repo.archive_expense(repo.add_expense(date(2025, 1, 1), "e", 1, "nick").id)
    repo.archive_template(repo.add_template("recipe", "r", "x").id)
    repo.add_note("active")
    # dead task + child + arch sub + grocery + meal + bill + note + expense + template
    assert repo.purge_archived() == 9
    assert repo.purge_archived() == 0
    assert [t.id for t in repo.list_tasks()] == [live.id]
    assert _count(repo, "subtasks") == 1
    assert len(repo.list_notes()) == 1
