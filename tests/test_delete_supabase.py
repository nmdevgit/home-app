"""Permanent delete methods (SupabaseRepository) against the in-memory fake client."""
from __future__ import annotations

from datetime import date

import pytest

from core.errors import BackendError, NotFoundError
from core.supabase_repo import SupabaseRepository
from tests.test_supabase_repo import FakeClient, FakeQuery


@pytest.fixture()
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture()
def repo(client: FakeClient) -> SupabaseRepository:
    return SupabaseRepository(client, "nick-id")


def test_delete_task_removes_its_subtasks(repo: SupabaseRepository, client: FakeClient) -> None:
    keep, gone = repo.add_task("keep"), repo.add_task("gone")
    repo.add_subtask(keep.id, "k")
    s = repo.add_subtask(gone.id, "a")
    repo.archive_subtask(s.id)
    repo.add_subtask(gone.id, "b")
    repo.delete_task(gone.id)
    assert [r["id"] for r in client.stores["tasks"]] == [keep.id]
    assert len(client.stores["subtasks"]) == 1
    with pytest.raises(NotFoundError):
        repo.delete_task(gone.id)


def test_each_delete_and_not_found(repo: SupabaseRepository, client: FakeClient) -> None:
    t = repo.add_task("t")
    sub = repo.add_subtask(t.id, "s")
    g = repo.add_grocery("g")
    m = repo.add_meal(date(2025, 1, 1), "m")
    b = repo.add_bill("b", 100, date(2025, 1, 1))
    n = repo.add_note("n")
    e = repo.add_expense(date(2025, 1, 1), "e", 100, "nick")
    tpl = repo.add_template("shopping", "x", "i")
    repo.archive_note(n.id)  # archived rows delete too
    pairs = [
        (repo.delete_subtask, sub.id), (repo.delete_grocery, g.id), (repo.delete_meal, m.id),
        (repo.delete_bill, b.id), (repo.delete_note, n.id), (repo.delete_expense, e.id),
        (repo.delete_template, tpl.id),
    ]
    for fn, row_id in pairs:
        fn(row_id)
        with pytest.raises(NotFoundError):
            fn(row_id)
    for table in ("subtasks", "grocery_items", "meals", "bills", "notes", "expenses", "templates"):
        assert client.stores[table] == []
    assert len(client.stores["tasks"]) == 1


def test_delete_checked_grocery(repo: SupabaseRepository, client: FakeClient) -> None:
    a, c = repo.add_grocery("a"), repo.add_grocery("c")
    repo.set_grocery_checked(a.id, True)
    repo.archive_checked_grocery()  # archived: must survive
    d = repo.add_grocery("d")
    repo.set_grocery_checked(d.id, True)
    assert repo.delete_checked_grocery() == 1
    assert sorted(r["name"] for r in client.stores["grocery_items"]) == ["a", "c"]
    assert c.id and repo.delete_checked_grocery() == 0


def test_purge_archived(repo: SupabaseRepository, client: FakeClient) -> None:
    live, dead = repo.add_task("live"), repo.add_task("dead")
    repo.add_subtask(live.id, "keep")
    repo.add_subtask(dead.id, "child")
    arch = repo.add_subtask(live.id, "arch")
    repo.archive_subtask(arch.id)
    repo.archive_task(dead.id)
    repo.archive_meal(repo.add_meal(date(2025, 1, 1), "m").id)
    repo.archive_bill(repo.add_bill("b", 1, date(2025, 1, 1)).id)
    repo.archive_note(repo.add_note("n").id)
    repo.archive_expense(repo.add_expense(date(2025, 1, 1), "e", 1, "nick").id)
    repo.archive_template(repo.add_template("recipe", "r", "x").id)
    repo.add_grocery("active")
    assert repo.purge_archived() == 8
    assert repo.purge_archived() == 0
    assert [r["id"] for r in client.stores["tasks"]] == [live.id]
    assert len(client.stores["subtasks"]) == 1
    assert len(client.stores["grocery_items"]) == 1


def test_delete_failure_is_wrapped(repo: SupabaseRepository) -> None:
    def boom(self: FakeQuery) -> None:
        raise RuntimeError("rls denied")

    original = FakeQuery.execute
    FakeQuery.execute = boom  # type: ignore[method-assign,assignment]
    try:
        with pytest.raises(BackendError):
            repo.delete_note("x")
    finally:
        FakeQuery.execute = original  # type: ignore[method-assign]
