"""SupabaseRepository against a tiny in-memory fake of the postgrest builder."""
from __future__ import annotations

import itertools
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from core import clock
from core.errors import BackendError, NotFoundError, ValidationError
from core.repo import Task
from core.supabase_repo import SupabaseRepository


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data


_CLOCK = itertools.count(1)


def _stamp() -> str:
    return f"2025-01-01T00:00:00.{next(_CLOCK):06d}Z"


class FakeQuery:
    def __init__(self, store: list[dict[str, Any]], op: str, payload: Any = None) -> None:
        self.store, self.op, self.payload = store, op, payload
        self.filters: list[tuple[str, str, Any, bool]] = []
        self.orders: list[tuple[str, bool]] = []
        self.max_rows: int | None = None
        self._negate = False

    @property
    def not_(self) -> FakeQuery:
        self._negate = True
        return self

    def select(self, _cols: str) -> FakeQuery:
        return self

    def _add(self, kind: str, col: str, val: Any) -> FakeQuery:
        self.filters.append((kind, col, val, self._negate))
        self._negate = False
        return self

    def eq(self, col: str, val: Any) -> FakeQuery:
        return self._add("eq", col, val)

    def is_(self, col: str, val: str) -> FakeQuery:
        return self._add("is", col, val)

    def gte(self, col: str, val: Any) -> FakeQuery:
        return self._add("gte", col, val)

    def lte(self, col: str, val: Any) -> FakeQuery:
        return self._add("lte", col, val)

    def order(self, col: str, desc: bool = False, **_kw: Any) -> FakeQuery:
        self.orders.append((col, desc))
        return self

    def limit(self, n: int) -> FakeQuery:
        self.max_rows = n
        return self

    def _match(self, row: dict[str, Any]) -> bool:
        for kind, col, val, negate in self.filters:
            got = row.get(col)
            if kind == "eq":
                ok = got == val
            elif kind == "is":
                ok = got is None  # only 'null' is used
            elif kind == "gte":
                ok = got is not None and got >= val
            else:
                ok = got is not None and got <= val
            if ok == negate:
                return False
        return True

    def execute(self) -> FakeResponse:
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for item in items:
                stamp = _stamp()
                row = {
                    "id": str(uuid.uuid4()),
                    "notes": "",
                    "status": "open",
                    "completed_at": None,
                    "archived_at": None,
                    "created_at": stamp,
                    "updated_at": stamp,
                    "checked": False,
                    "due_date": None,
                    "priority": "normal",
                    "rotate": False,
                    "category": "other",
                    "quantity": "",
                    "pinned": False,
                    "body": "",
                    "ingredients": "",
                    "slot": "dinner",
                    "last_paid_on": None,
                    **item,
                }
                self.store.append(row)
                out.append(dict(row))
            return FakeResponse(out)
        rows = [r for r in self.store if self._match(r)]
        for col, desc in reversed(self.orders):
            rows.sort(
                key=lambda r, c=col: (r.get(c) is None, 0 if r.get(c) is None else r[c]),
                reverse=desc,
            )
        if self.max_rows is not None:
            rows = rows[: self.max_rows]
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
                if "updated_at" in r:  # mimics the notes trigger
                    r["updated_at"] = _stamp()
        return FakeResponse([dict(r) for r in rows])


class FakeTable:
    def __init__(self, store: list[dict[str, Any]], log: list[tuple[str, str]], name: str) -> None:
        self.store, self.log, self.name = store, log, name

    def select(self, cols: str) -> FakeQuery:
        self.log.append((self.name, "select"))
        return FakeQuery(self.store, "select").select(cols)

    def insert(self, payload: Any) -> FakeQuery:
        self.log.append((self.name, "insert"))
        return FakeQuery(self.store, "insert", payload)

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.log.append((self.name, "update"))
        return FakeQuery(self.store, "update", payload)

    def delete(self) -> None:  # the repo must never call this
        self.log.append((self.name, "delete"))
        raise AssertionError("delete called")


class FakeRpc:
    def __init__(self, value: Any) -> None:
        self.value = value

    def execute(self) -> FakeResponse:
        return FakeResponse(self.value)


class FakeClient:
    def __init__(self) -> None:
        self.stores: dict[str, list[dict[str, Any]]] = {
            name: [] for name in ("tasks", "grocery_items", "meals", "bills", "notes")
        }
        self.log: list[tuple[str, str]] = []
        self.db_size: Any = 12345

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.stores[name], self.log, name)

    def rpc(self, name: str) -> FakeRpc:
        assert name == "db_size"
        self.log.append((name, "rpc"))
        return FakeRpc(self.db_size)


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


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    day = date(2025, 1, 1)
    monkeypatch.setattr(clock, "today", lambda tz_name=None: day)
    return day


def test_priority_rotate_payload_and_swap(repo: SupabaseRepository, client: FakeClient) -> None:
    task = repo.add_task(
        "Bins", assignee="nick", due_date=date(2025, 1, 5), recurrence="weekly",
        priority="high", rotate=True,
    )
    assert task.priority == "high" and task.rotate
    repo.complete_task(task.id)
    nxt = client.stores["tasks"][1]
    assert nxt["assignee"] == "natalie" and nxt["priority"] == "high" and nxt["rotate"] is True
    with pytest.raises(ValidationError):
        repo.add_task("x", priority="urgent")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repo.update_task(task.id, rotate="yes")


def test_limit_clamped_and_sent(repo: SupabaseRepository) -> None:
    for i in range(3):
        repo.add_task(f"t{i}")
    assert len(repo.list_tasks(limit=2)) == 2
    assert len(repo.list_tasks(limit=0)) == 1  # clamped up to 1
    assert len(repo.list_tasks(limit=10_000)) == 3


def test_done_and_archived_tasks_restore(repo: SupabaseRepository) -> None:
    task = repo.add_task("a")
    repo.complete_task(task.id)
    assert [t.id for t in repo.list_done_tasks(datetime(2000, 1, 1, tzinfo=UTC))] == [task.id]
    assert repo.list_done_tasks(datetime(2999, 1, 1, tzinfo=UTC)) == []
    with pytest.raises(ValidationError):
        repo.list_done_tasks(datetime(2000, 1, 1))
    repo.archive_task(task.id)
    assert [t.id for t in repo.list_archived_tasks()] == [task.id]
    assert repo.restore_task(task.id).id == task.id
    assert repo.list_archived_tasks() == []
    with pytest.raises(NotFoundError):
        repo.restore_task(task.id)


def test_grocery_category_update_restore_frequent(repo: SupabaseRepository) -> None:
    a = repo.add_grocery("Milk", category="dairy")
    repo.add_grocery("milk", category="other")
    repo.add_grocery("Eggs")
    assert repo.update_grocery(a.id, category="drinks", quantity="1").category == "drinks"
    with pytest.raises(ValidationError):
        repo.update_grocery(a.id, category="nope")
    with pytest.raises(ValidationError):
        repo.add_grocery("x", category="nope")  # type: ignore[arg-type]
    repo.set_grocery_checked(a.id, True)
    repo.archive_checked_grocery()
    assert [g.id for g in repo.list_archived_grocery()] == [a.id]
    freq = repo.frequent_grocery()
    assert freq[0] == ("milk", "other")  # 2 uses, newest casing/category
    assert repo.restore_grocery(a.id).checked
    assert repo.list_archived_grocery() == []


def test_meals_flow_and_grocery_dedupe(repo: SupabaseRepository, client: FakeClient) -> None:
    repo.add_grocery("Onion")
    meal = repo.add_meal(date(2025, 1, 2), "Pasta", "onion\nPasta\n pasta \n\nSauce")
    assert repo.meal_to_grocery(meal.id) == 2  # onion exists, pasta dup in meal
    names = [r["name"] for r in client.stores["grocery_items"]]
    assert names == ["Onion", "Pasta", "Sauce"]
    assert client.stores["grocery_items"][1]["added_by"] == "nick-id"
    assert repo.meal_to_grocery(meal.id) == 0
    lunch = repo.add_meal(date(2025, 1, 2), "Soup", slot="lunch")
    got = repo.list_meals(date(2025, 1, 1), date(2025, 1, 31))
    assert [m.id for m in got] == [lunch.id, meal.id]  # lunch before dinner
    assert repo.update_meal(meal.id, title="Penne").title == "Penne"
    repo.archive_meal(meal.id)
    assert [m.id for m in repo.list_meals(date(2025, 1, 1), date(2025, 1, 31))] == [lunch.id]
    with pytest.raises(NotFoundError):
        repo.meal_to_grocery(meal.id)
    with pytest.raises(ValidationError):
        repo.add_meal(date(2025, 1, 1), "x", "\n".join(["i"] * 41))


def test_bills_flow(repo: SupabaseRepository, client: FakeClient) -> None:
    bill = repo.add_bill("Rent", 150_000, date(2025, 1, 31), "monthly")
    assert client.stores["bills"][0]["due_date"] == "2025-01-31"
    paid = repo.mark_bill_paid(bill.id)
    assert paid.due_date == date(2025, 2, 28) and paid.last_paid_on == date(2025, 1, 1)
    one = repo.add_bill("Fine", 500, date(2025, 3, 1), "none")
    assert repo.mark_bill_paid(one.id).due_date == date(2025, 3, 1)
    assert repo.update_bill(one.id, amount_cents=600).amount_cents == 600
    with pytest.raises(ValidationError):
        repo.add_bill("x", -1, date(2025, 1, 1))
    with pytest.raises(ValidationError):
        repo.add_bill("x", 100_000_001, date(2025, 1, 1))
    repo.archive_bill(one.id)
    assert [b.id for b in repo.list_bills()] == [bill.id]


def test_notes_flow(repo: SupabaseRepository) -> None:
    n1 = repo.add_note("one")
    n2 = repo.add_note("two")
    pinned = repo.add_note("pin", pinned=True)
    assert [n.id for n in repo.list_notes()] == [pinned.id, n2.id, n1.id]
    repo.update_note(n1.id, body="edited")
    assert [n.id for n in repo.list_notes()] == [pinned.id, n1.id, n2.id]
    with pytest.raises(ValidationError):
        repo.update_note(n1.id, body="x" * 5001)
    repo.archive_note(n1.id)
    assert n1.id not in [n.id for n in repo.list_notes()]


def test_storage_usage(repo: SupabaseRepository, client: FakeClient) -> None:
    usage = repo.storage_usage()
    assert usage.used_bytes == 12345 and usage.limit_bytes == 500 * 1024 * 1024
    client.db_size = [{"db_size": 99}]
    assert repo.storage_usage().used_bytes == 99
    client.db_size = None
    with pytest.raises(BackendError):
        repo.storage_usage()


def test_new_methods_never_delete(repo: SupabaseRepository, client: FakeClient) -> None:
    note = repo.add_note("n")
    repo.archive_note(note.id)
    assert all(op != "delete" for _, op in client.log)
