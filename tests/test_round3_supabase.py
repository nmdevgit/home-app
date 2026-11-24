"""Round 3 SupabaseRepository methods against the in-memory fake client."""
from __future__ import annotations

from datetime import date

import pytest

from core.errors import NotFoundError, ValidationError
from core.supabase_repo import SupabaseRepository
from tests.test_supabase_repo import FakeClient


@pytest.fixture()
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture()
def repo(client: FakeClient) -> SupabaseRepository:
    return SupabaseRepository(client, "nick-id")


def test_completed_by_set_and_cleared(repo: SupabaseRepository, client: FakeClient) -> None:
    task = repo.add_task("x")
    assert task.completed_by is None
    done = repo.complete_task(task.id)
    assert done.completed_by == "nick-id"
    assert client.stores["tasks"][0]["completed_by"] == "nick-id"
    assert repo.reopen_task(task.id).completed_by is None


def test_subtasks_one_select_and_lifecycle(repo: SupabaseRepository, client: FakeClient) -> None:
    a, b = repo.add_task("A"), repo.add_task("B")
    s1 = repo.add_subtask(a.id, " one ")
    repo.add_subtask(b.id, "two")
    assert s1.title == "one" and client.stores["subtasks"][0]["created_by"] == "nick-id"
    client.log.clear()
    assert len(repo.list_subtasks([a.id, b.id, a.id])) == 2
    assert client.log == [("subtasks", "select")]
    assert repo.set_subtask_done(s1.id, True).done is True
    repo.archive_subtask(s1.id)
    assert [s.title for s in repo.list_subtasks([a.id, b.id])] == ["two"]
    assert repo.list_subtasks([]) == []


def test_subtask_errors(repo: SupabaseRepository, client: FakeClient) -> None:
    task = repo.add_task("A")
    with pytest.raises(ValidationError):
        repo.add_subtask(task.id, "x" * 201)
    with pytest.raises(NotFoundError):
        repo.add_subtask("missing", "ok")
    with pytest.raises(NotFoundError):
        repo.set_subtask_done("missing", True)
    assert client.stores["subtasks"] == []


def test_expenses(repo: SupabaseRepository, client: FakeClient) -> None:
    repo.add_expense(date(2025, 1, 1), "old", 100, "nick")
    new = repo.add_expense(date(2025, 3, 1), "new", 250, "natalie", "other_only")
    assert client.stores["expenses"][1]["day"] == "2025-03-01"
    assert [e.description for e in repo.list_expenses()] == ["new", "old"]
    assert [e.description for e in repo.list_expenses(since=date(2025, 2, 1))] == ["new"]
    assert new.paid_by == "natalie" and new.split == "other_only" and new.amount_cents == 250
    repo.archive_expense(new.id)
    assert [e.description for e in repo.list_expenses()] == ["old"]
    with pytest.raises(NotFoundError):
        repo.archive_expense(new.id)


@pytest.mark.parametrize("amount", [0, -1, 100_000_001, 1.5, True])
def test_expense_validation_blocks_request(
    repo: SupabaseRepository, client: FakeClient, amount: object
) -> None:
    with pytest.raises(ValidationError):
        repo.add_expense(date(2025, 1, 1), "x", amount, "nick")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repo.add_expense(date(2025, 1, 1), "x", 5, "eve")  # type: ignore[arg-type]
    assert client.log == []


def test_templates_and_to_grocery(repo: SupabaseRepository, client: FakeClient) -> None:
    repo.add_grocery("Milk")
    t = repo.add_template("shopping", "Weekly", "milk\neggs\nEGGS\nbread")
    repo.add_template("recipe", "Pasta", "pasta")
    assert [x.name for x in repo.list_templates()] == ["Pasta", "Weekly"]
    assert [x.name for x in repo.list_templates("shopping")] == ["Weekly"]
    assert repo.template_to_grocery(t.id) == 2
    assert sorted(g.name for g in repo.list_grocery()) == ["Milk", "bread", "eggs"]
    assert repo.template_to_grocery(t.id) == 0
    assert repo.update_template(t.id, name="Big").name == "Big"
    repo.archive_template(t.id)
    with pytest.raises(NotFoundError):
        repo.template_to_grocery(t.id)
    with pytest.raises(ValidationError):
        repo.add_template("meal", "x", "")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repo.add_template("shopping", "x", "\n".join("a" * 5 for _ in range(61)))


def test_list_members(repo: SupabaseRepository, client: FakeClient) -> None:
    client.stores["household_members"] += [
        {"user_id": "u1", "name": "nick"},
        {"user_id": "u2", "name": "natalie"},
        {"user_id": "u3", "name": "stranger"},
    ]
    assert repo.list_members() == {"u1": "nick", "u2": "natalie"}


def test_export_whitelist_and_paging(repo: SupabaseRepository, client: FakeClient) -> None:
    for i in range(7):
        repo.add_task(f"t{i}")
    client.stores["tasks"][0]["archived_at"] = "2025-01-01T00:00:00Z"
    rows = repo.export_rows("tasks")
    assert len(rows) == 7  # archived included
    assert len(repo.export_rows("tasks", limit=3)) == 3
    assert len(repo.export_rows("tasks", limit=0)) == 1
    with pytest.raises(ValidationError):
        repo.export_rows("auth.users")
    with pytest.raises(ValidationError):
        repo.export_rows("household_members")


def test_export_pages_beyond_1000(repo: SupabaseRepository, client: FakeClient) -> None:
    for i in range(1500):
        client.stores["notes"].append(
            {"id": f"{i:05d}", "created_at": f"2025-01-01T00:{i // 60:02d}:{i % 60:02d}Z"}
        )
    assert len(repo.export_rows("notes")) == 1500
    assert len(repo.export_rows("notes", limit=10**6)) == 1500


