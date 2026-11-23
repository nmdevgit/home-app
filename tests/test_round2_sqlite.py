"""Round 2 repository features against SQLite in-memory."""
from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from core import clock, rules
from core.errors import NotFoundError, ValidationError
from core.sqlite_repo import SqliteRepository


@pytest.fixture(autouse=True)
def ticking_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strictly increasing timestamps (the OS clock can repeat within a test)."""
    state = {"t": datetime(2025, 1, 1, tzinfo=UTC)}

    def tick() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    monkeypatch.setattr(rules, "utc_now", tick)


def _count(repo: SqliteRepository, table: str) -> int:
    return repo._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---- tasks ---------------------------------------------------------------
def test_priority_and_rotate_roundtrip(repo: SqliteRepository) -> None:
    task = repo.add_task("a", priority="high", rotate=True)
    assert task.priority == "high" and task.rotate is True
    upd = repo.update_task(task.id, priority="low", rotate=False)
    assert upd.priority == "low" and upd.rotate is False
    assert repo.add_task("b").priority == "normal"


@pytest.mark.parametrize(
    "kwargs", [{"priority": "urgent"}, {"rotate": "yes"}, {"rotate": 1}, {"priority": None}]
)
def test_priority_rotate_validation(repo: SqliteRepository, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        repo.add_task("a", **kwargs)  # type: ignore[arg-type]
    task = repo.add_task("ok")
    with pytest.raises(ValidationError):
        repo.update_task(task.id, **kwargs)


@pytest.mark.parametrize(
    ("start", "expected"),
    [("nick", "natalie"), ("natalie", "nick"), ("either", "either")],
)
def test_rotate_swaps_assignee(repo: SqliteRepository, start: str, expected: str) -> None:
    task = repo.add_task(
        "chore", assignee=start, due_date=date(2025, 1, 3), recurrence="weekly",  # type: ignore[arg-type]
        rotate=True, priority="high",
    )
    repo.complete_task(task.id)
    repo.complete_task(task.id)  # idempotency guard still holds
    (nxt,) = repo.list_tasks()
    assert nxt.assignee == expected and nxt.rotate and nxt.priority == "high"
    assert _count(repo, "tasks") == 2


def test_no_rotate_keeps_assignee(repo: SqliteRepository) -> None:
    task = repo.add_task("c", assignee="nick", due_date=date(2025, 1, 3), recurrence="daily")
    repo.complete_task(task.id)
    assert repo.list_tasks()[0].assignee == "nick"


def test_list_limit_clamped(repo: SqliteRepository) -> None:
    for i in range(3):
        repo.add_task(f"t{i}")
    assert len(repo.list_tasks(limit=2)) == 2
    assert len(repo.list_tasks(limit=0)) == 1
    assert len(repo.list_tasks(limit=-5)) == 1
    assert len(repo.list_tasks(limit=10**9)) == 3
    with pytest.raises(ValidationError):
        repo.list_tasks(limit="5")  # type: ignore[arg-type]
    assert rules.clamp_limit(10**9) == 500


def test_list_done_tasks(repo: SqliteRepository) -> None:
    a, b, c = (repo.add_task(n) for n in "abc")
    repo.complete_task(a.id)
    repo.complete_task(b.id)
    now = rules.utc_now()
    done = repo.list_done_tasks(now - timedelta(hours=1))
    assert [t.id for t in done] == [b.id, a.id]  # newest first
    assert repo.list_done_tasks(now + timedelta(hours=1)) == []
    assert len(repo.list_done_tasks(now - timedelta(hours=1), limit=1)) == 1
    assert c.id not in [t.id for t in done]
    repo.archive_task(a.id)
    assert [t.id for t in repo.list_done_tasks(now - timedelta(hours=1))] == [b.id]
    with pytest.raises(ValidationError):
        repo.list_done_tasks(datetime(2025, 1, 1))


def test_archive_restore_task_roundtrip(repo: SqliteRepository) -> None:
    task = repo.add_task("x", priority="high")
    repo.archive_task(task.id)
    assert repo.list_tasks() == []
    assert [t.id for t in repo.list_archived_tasks()] == [task.id]
    assert repo.restore_task(task.id) == task
    assert repo.list_archived_tasks() == [] and repo.list_tasks() == [task]
    with pytest.raises(NotFoundError):
        repo.restore_task(task.id)  # not archived
    with pytest.raises(NotFoundError):
        repo.restore_task("missing")
    assert _count(repo, "tasks") == 1


# ---- grocery -------------------------------------------------------------
def test_grocery_category_and_update(repo: SqliteRepository) -> None:
    item = repo.add_grocery("Milk", "2L", category="dairy")
    assert item.category == "dairy" and repo.add_grocery("x").category == "other"
    upd = repo.update_grocery(item.id, name=" Oat milk ", quantity="1", category="drinks")
    assert (upd.name, upd.quantity, upd.category) == ("Oat milk", "1", "drinks")
    for bad in ({"category": "toys"}, {"name": ""}, {"name": "x" * 201}, {"checked": True}):
        with pytest.raises(ValidationError):
            repo.update_grocery(item.id, **bad)
    with pytest.raises(ValidationError):
        repo.add_grocery("y", category="toys")  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        repo.update_grocery("missing", name="z")


def test_grocery_archive_restore_and_limit(repo: SqliteRepository) -> None:
    items = [repo.add_grocery(f"i{n}") for n in range(3)]
    for it in items[:2]:
        repo.set_grocery_checked(it.id, True)
    assert repo.archive_checked_grocery() == 2
    assert len(repo.list_archived_grocery()) == 2
    assert len(repo.list_archived_grocery(limit=1)) == 1
    assert len(repo.list_grocery(limit=0)) == 1
    restored = repo.restore_grocery(items[0].id)
    assert restored.id == items[0].id
    assert len(repo.list_grocery()) == 2
    with pytest.raises(NotFoundError):
        repo.restore_grocery(items[0].id)


def test_frequent_grocery(repo: SqliteRepository) -> None:
    repo.add_grocery("eggs", category="dairy")
    repo.add_grocery("Milk", category="dairy")
    repo.add_grocery("MILK", category="drinks")
    repo.add_grocery("bread", category="bakery")
    repo.add_grocery("Milk ", category="drinks")
    it = repo.add_grocery("eggs", category="other")
    repo.set_grocery_checked(it.id, True)
    repo.archive_checked_grocery()  # archived rows still count
    freq = repo.frequent_grocery()
    assert [n.lower() for n, _ in freq] == ["milk", "eggs", "bread"]  # 3, 2, 1
    by_name = {n.lower(): (n, c) for n, c in freq}
    assert by_name["milk"] == ("Milk", "drinks")  # latest row's display name + category
    assert by_name["eggs"] == ("eggs", "other")
    assert len(repo.frequent_grocery(limit=1)) == 1
    assert repo.frequent_grocery(limit=0) != []  # clamped to 1


def test_frequent_scans_newest_500_only(repo: SqliteRepository) -> None:
    repo.add_grocery("ancient")
    repo._conn.execute("UPDATE grocery_items SET created_at = '2000-01-01T00:00:00+00:00'")
    for _ in range(500):
        repo.add_grocery("new")
    assert [n for n, _ in repo.frequent_grocery()] == ["new"]


# ---- meals ---------------------------------------------------------------
def test_meal_crud_order_and_validation(repo: SqliteRepository) -> None:
    d = date(2025, 1, 10)
    dinner = repo.add_meal(d, "Pasta", " a\n\n b ")
    lunch = repo.add_meal(d, "Soup", slot="lunch")
    other = repo.add_meal(date(2025, 1, 9), "Toast", slot="breakfast")
    assert dinner.ingredients == "a\nb"
    got = repo.list_meals(date(2025, 1, 9), d)
    assert [m.id for m in got] == [other.id, lunch.id, dinner.id]
    assert [m.id for m in repo.list_meals(d, d)] == [lunch.id, dinner.id]
    assert len(repo.list_meals(date(2025, 1, 1), d, limit=1)) == 1
    upd = repo.update_meal(dinner.id, title="Penne", slot="lunch", day=date(2025, 1, 11))
    assert (upd.title, upd.slot, upd.day) == ("Penne", "lunch", date(2025, 1, 11))
    bads = [
        {"title": ""}, {"title": "x" * 201}, {"slot": "brunch"}, {"day": "2025-01-01"},
        {"day": datetime(2025, 1, 1)}, {"ingredients": "\n".join(["i"] * 41)},
        {"ingredients": "x" * 2001}, {"ingredients": ("y" * 100 + "\n") * 21},
        {"created_by": "me"},
    ]
    for bad in bads:
        with pytest.raises(ValidationError):
            repo.update_meal(dinner.id, **bad)
    with pytest.raises(ValidationError):
        repo.add_meal(d, "t", slot="brunch")  # type: ignore[arg-type]
    assert repo.add_meal(d, "forty", "\n".join(["i"] * 40)).ingredients.count("\n") == 39
    repo.archive_meal(lunch.id)
    assert lunch.id not in [m.id for m in repo.list_meals(d, d)]
    with pytest.raises(NotFoundError):
        repo.archive_meal(lunch.id)
    assert _count(repo, "meals") == 4


def test_meal_to_grocery_dedupes(repo: SqliteRepository) -> None:
    repo.add_grocery("Onion")
    gone = repo.add_grocery("Garlic")
    repo.set_grocery_checked(gone.id, True)
    repo.archive_checked_grocery()  # archived names do not block a re-add
    meal = repo.add_meal(date(2025, 1, 2), "Stew", "onion\nGARLIC\nBeef\nbeef\nCarrot")
    assert repo.meal_to_grocery(meal.id) == 3
    names = [g.name for g in repo.list_grocery()]
    assert sorted(names) == ["Beef", "Carrot", "GARLIC", "Onion"]
    assert all(g.category == "other" for g in repo.list_grocery() if g.name != "Onion")
    assert repo.meal_to_grocery(meal.id) == 0
    empty = repo.add_meal(date(2025, 1, 2), "Water")
    assert repo.meal_to_grocery(empty.id) == 0
    with pytest.raises(NotFoundError):
        repo.meal_to_grocery("missing")


# ---- bills ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("recurrence", "due", "expected"),
    [
        ("weekly", date(2025, 1, 10), date(2025, 1, 17)),
        ("fortnightly", date(2025, 1, 10), date(2025, 1, 24)),
        ("monthly", date(2025, 1, 10), date(2025, 2, 10)),
        ("monthly", date(2025, 1, 31), date(2025, 2, 28)),
        ("yearly", date(2025, 3, 5), date(2026, 3, 5)),
        ("yearly", date(2024, 2, 29), date(2025, 2, 28)),
        ("none", date(2025, 1, 10), date(2025, 1, 10)),
        ("weekly", date(2024, 12, 1), date(2025, 1, 5)),  # overdue: rolls past today
        ("monthly", date(2024, 11, 30), date(2025, 1, 30)),
    ],
)
def test_mark_bill_paid_advances(
    repo: SqliteRepository, recurrence: str, due: date, expected: date
) -> None:
    bill = repo.add_bill("b", 1000, due, recurrence)  # type: ignore[arg-type]
    paid = repo.mark_bill_paid(bill.id)
    assert paid.due_date == expected
    assert paid.last_paid_on == clock.today()


def test_bill_crud_validation_archive(repo: SqliteRepository) -> None:
    bill = repo.add_bill(" Rent ", 0, date(2025, 2, 1))
    assert bill.name == "Rent" and bill.recurrence == "monthly" and bill.last_paid_on is None
    assert repo.add_bill("max", 100_000_000, date(2025, 2, 1)).amount_cents == 100_000_000
    upd = repo.update_bill(bill.id, amount_cents=5, recurrence="yearly", name="R")
    assert (upd.amount_cents, upd.recurrence, upd.name) == (5, "yearly", "R")
    for bad in (
        {"amount_cents": -1}, {"amount_cents": 100_000_001}, {"amount_cents": 1.5},
        {"amount_cents": True}, {"amount_cents": "5"}, {"name": ""}, {"name": "x" * 201},
        {"recurrence": "daily"}, {"due_date": None}, {"due_date": "2025-01-01"},
        {"last_paid_on": date(2025, 1, 1)},
    ):
        with pytest.raises(ValidationError):
            repo.update_bill(bill.id, **bad)
    with pytest.raises(ValidationError):
        repo.add_bill("x", -1, date(2025, 1, 1))
    with pytest.raises(ValidationError):
        repo.add_bill("x", 1, date(2025, 1, 1), "daily")  # type: ignore[arg-type]
    later = repo.add_bill("A", 1, date(2025, 3, 1))
    assert {b.id for b in repo.list_bills()} >= {bill.id, later.id}
    assert len(repo.list_bills(limit=1)) == 1
    repo.archive_bill(bill.id)
    assert bill.id not in [b.id for b in repo.list_bills()]
    with pytest.raises(NotFoundError):
        repo.mark_bill_paid(bill.id)


def test_monthly_equivalent_cents() -> None:
    assert rules.monthly_equivalent_cents(1200, "monthly") == 1200
    assert rules.monthly_equivalent_cents(1200, "weekly") == 5200
    assert rules.monthly_equivalent_cents(1200, "fortnightly") == 2600
    assert rules.monthly_equivalent_cents(1200, "yearly") == 100
    assert rules.monthly_equivalent_cents(1200, "none") == 0
    assert rules.monthly_equivalent_cents(1, "weekly") == 4  # 4.33 -> 4
    assert rules.monthly_equivalent_cents(7, "yearly") == 1  # 0.58 -> 1 (half up)
    with pytest.raises(ValidationError):
        rules.monthly_equivalent_cents(1, "daily")


# ---- notes ---------------------------------------------------------------
def test_notes_ordering_update_archive(repo: SqliteRepository) -> None:
    n1 = repo.add_note("one", "b")
    n2 = repo.add_note("two")
    pin = repo.add_note("pin", pinned=True)
    assert [n.id for n in repo.list_notes()] == [pin.id, n2.id, n1.id]
    upd = repo.update_note(n1.id, body="edited", pinned=True)
    assert upd.updated_at > n1.updated_at and upd.created_at == n1.created_at
    assert [n.id for n in repo.list_notes()] == [n1.id, pin.id, n2.id]  # pinned, newest first
    assert len(repo.list_notes(limit=2)) == 2
    for bad in ({"title": ""}, {"body": "x" * 5001}, {"pinned": "yes"}, {"created_by": "x"}):
        with pytest.raises(ValidationError):
            repo.update_note(n1.id, **bad)
    assert repo.add_note("big", "x" * 5000).body == "x" * 5000
    with pytest.raises(ValidationError):
        repo.add_note("t" * 201)
    repo.archive_note(n2.id)
    assert n2.id not in [n.id for n in repo.list_notes()]
    with pytest.raises(NotFoundError):
        repo.update_note(n2.id, title="z")


# ---- storage -------------------------------------------------------------
def test_storage_usage_memory_and_file(repo: SqliteRepository, tmp_path) -> None:
    usage = repo.storage_usage()
    assert usage.used_bytes > 0 and usage.limit_bytes == 500 * 1024 * 1024
    on_disk = SqliteRepository(tmp_path / "x.db")
    assert on_disk.storage_usage().used_bytes == (tmp_path / "x.db").stat().st_size


def test_old_database_file_is_migrated(tmp_path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL "
        "DEFAULT '', assignee TEXT NOT NULL DEFAULT 'either', due_date TEXT, recurrence TEXT "
        "NOT NULL DEFAULT 'none', status TEXT NOT NULL DEFAULT 'open', created_by TEXT NOT NULL,"
        " created_at TEXT NOT NULL, completed_at TEXT, archived_at TEXT);"
        "CREATE TABLE grocery_items (id TEXT PRIMARY KEY, name TEXT NOT NULL, quantity TEXT NOT "
        "NULL DEFAULT '', checked INTEGER NOT NULL DEFAULT 0, added_by TEXT NOT NULL, "
        "created_at TEXT NOT NULL, archived_at TEXT);"
    )
    conn.close()
    repo = SqliteRepository(path)
    assert repo.add_task("t", priority="low").priority == "low"
    assert repo.add_grocery("g", category="meat").category == "meat"


# ---- no hard deletes -----------------------------------------------------
def test_no_repo_method_deletes_rows() -> None:
    import core.sqlite_repo as mod
    import core.supabase_repo as smod

    for module in (mod, smod):
        source = inspect.getsource(module).lower()
        assert "delete from" not in source and ".delete(" not in source
    repo = SqliteRepository(":memory:", user_id="u")
    repo.add_task("t")
    repo.add_grocery("g")
    repo.add_meal(date(2025, 1, 1), "m")
    repo.add_bill("b", 1, date(2025, 1, 1))
    repo.add_note("n")
    for table in ("tasks", "grocery_items", "meals", "bills", "notes"):
        with pytest.raises(sqlite3.DatabaseError):
            repo._conn.execute(f"DELETE FROM {table}")
