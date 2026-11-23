"""SupabaseRepository against a tiny in-memory fake of the postgrest builder."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from core.errors import BackendError, NotFoundError, ValidationError
from core.repo import Task
from core.supabase_repo import SupabaseRepository


class FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str, payload: Any = None) -> None:
        self.store, self.op, self.payload = store, op, payload
        self.filters: list[tuple[str, str, Any]] = []
        self.orders: list[str] = []

    def select(self, _cols: str) -> FakeQuery:
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        self.filters.append(("eq", col, val))
        return self

    def is_(self, col: str, val: str) -> FakeQuery:
        self.filters.append(("is", col, val))
        return self

    def order(self, col: str, **_kw: Any) -> FakeQuery:
        self.orders.append(col)
        return self

    def _match(self, row: dict[str, Any]) -> bool:
        for kind, col, val in self.filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "is" and val == "null" and row.get(col) is not None:
                return False
        return True

    def execute(self) -> FakeResponse:
        if self.op == "insert":
            row = {
                "id": str(uuid.uuid4()),
                "notes": "",
                "status": "open",
                "completed_at": None,
                "archived_at": None,
                "created_at": "2025-01-01T00:00:00Z",
                "checked": False,
                "due_date": None,
                **self.payload,
            }
            self.store.append(row)
            return FakeResponse([dict(row)])
        rows = [r for r in self.store if self._match(r)]
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
        return FakeResponse([dict(r) for r in rows])


class FakeTable:
    def __init__(self, store: list[dict[str, Any]], log: list[tuple[str, str]], name: str) -> None:
        self.store, self.log, self.name = store, log, name

    def select(self, cols: str) -> FakeQuery:
        self.log.append((self.name, "select"))
        return FakeQuery(self.store, "select").select(cols)

    def insert(self, payload: dict[str, Any]) -> FakeQuery:
        self.log.append((self.name, "insert"))
        return FakeQuery(self.store, "insert", payload)

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.log.append((self.name, "update"))
        return FakeQuery(self.store, "update", payload)

    def delete(self) -> None:  # the repo must never call this
        self.log.append((self.name, "delete"))
        raise AssertionError("delete called")


class FakeClient:
    def __init__(self) -> None:
        self.stores: dict[str, list[dict[str, Any]]] = {"tasks": [], "grocery_items": []}
        self.log: list[tuple[str, str]] = []

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.stores[name], self.log, name)


@pytest.fixture()
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture()
def repo(client: FakeClient) -> SupabaseRepository:
    return SupabaseRepository(client, "nick-id")


def test_add_task_sends_validated_payload(repo: SupabaseRepository, client: FakeClient) -> None:
    task = _add(repo, "  Dishes ", due=date(2025, 2, 3))
    row = client.stores["tasks"][0]
    assert row["title"] == "Dishes"
    assert row["due_date"] == "2025-02-03"  # serialised, not a date object
    assert row["created_by"] == "nick-id"
    assert task.created_at.tzinfo is not None


def _add(repo: SupabaseRepository, title: str, due: date | None = None, rec: str = "none") -> Task:
    return repo.add_task(title, assignee="nick", due_date=due, recurrence=rec)  # type: ignore[arg-type]


def test_validation_blocks_request(repo: SupabaseRepository, client: FakeClient) -> None:
    with pytest.raises(ValidationError):
        repo.add_task("")
    with pytest.raises(ValidationError):
        repo.add_grocery(" ")
    assert client.log == []  # never reached the network


def test_recurring_complete_creates_next(repo: SupabaseRepository, client: FakeClient) -> None:
    task = _add(repo, "Bins", due=date(2025, 1, 31), rec="monthly")
    done = repo.complete_task(task.id)
    assert done.status == "done"
    rows = client.stores["tasks"]
    assert len(rows) == 2
    assert rows[1]["due_date"] == "2025-02-28" and rows[1]["status"] == "open"
    # Completing again must not create a third row.
    repo.complete_task(task.id)
    assert len(client.stores["tasks"]) == 2


def test_archive_hides_task(repo: SupabaseRepository, client: FakeClient) -> None:
    task = _add(repo, "x")
    repo.archive_task(task.id)
    assert repo.list_tasks(include_done=True) == []
    assert client.stores["tasks"][0]["archived_at"] is not None
    with pytest.raises(NotFoundError):
        repo.archive_task(task.id)


def test_grocery_flow_and_no_delete(repo: SupabaseRepository, client: FakeClient) -> None:
    item = repo.add_grocery("Milk", "2L")
    assert client.stores["grocery_items"][0]["added_by"] == "nick-id"
    assert repo.set_grocery_checked(item.id, True).checked
    assert repo.archive_checked_grocery() == 1
    assert repo.list_grocery() == []
    assert all(op != "delete" for _, op in client.log)


def test_backend_failure_is_wrapped(repo: SupabaseRepository, client: FakeClient) -> None:
    def boom(self: FakeQuery) -> FakeResponse:
        raise RuntimeError("network down")

    FakeQuery.execute, original = boom, FakeQuery.execute  # type: ignore[method-assign]
    try:
        with pytest.raises(BackendError):
            repo.list_tasks()
    finally:
        FakeQuery.execute = original  # type: ignore[method-assign]
