"""Round 3 repository features on SQLite: completed_by, subtasks, expenses, templates,
members, export, and the no-delete guarantee."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from core.errors import NotFoundError, ValidationError
from core.repo import EXPORT_TABLES
from core.sqlite_repo import SqliteRepository

# ---- completed_by -------------------------------------------------------------


def test_complete_sets_completed_by_and_reopen_clears(repo: SqliteRepository) -> None:
    task = repo.add_task("Dishes")
    assert task.completed_by is None
    done = repo.complete_task(task.id)
    assert done.completed_by == "nick-id"
    assert repo.reopen_task(task.id).completed_by is None


def test_completed_by_not_updatable_via_update_task(repo: SqliteRepository) -> None:
    task = repo.add_task("x")
    with pytest.raises(ValidationError):
        repo.update_task(task.id, completed_by="natalie-id")


def test_completed_by_listed_in_done_tasks(repo: SqliteRepository) -> None:
    from core import rules

    t = repo.add_task("x")
    repo.complete_task(t.id)
    rows = repo.list_done_tasks(rules.utc_now().replace(year=2000))
    assert [r.completed_by for r in rows] == ["nick-id"]


def test_old_sqlite_file_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL "
        "DEFAULT '', assignee TEXT NOT NULL DEFAULT 'either', due_date TEXT, recurrence TEXT "
        "NOT NULL DEFAULT 'none', status TEXT NOT NULL DEFAULT 'open', created_by TEXT NOT NULL,"
        " created_at TEXT NOT NULL, completed_at TEXT, archived_at TEXT)"
    )
    conn.commit()
    conn.close()
    repo = SqliteRepository(path, user_id="u1")
    task = repo.add_task("migrated")
    assert repo.complete_task(task.id).completed_by == "u1"
    assert repo.list_templates() == []


# ---- subtasks -------------------------------------------------------------------


def test_subtasks_add_list_done_archive(repo: SqliteRepository) -> None:
    a, b = repo.add_task("A"), repo.add_task("B")
    s1 = repo.add_subtask(a.id, "  one ")
    s2 = repo.add_subtask(a.id, "two")
    repo.add_subtask(b.id, "other")
    assert s1.title == "one" and not s1.done and s1.task_id == a.id
    assert [s.title for s in repo.list_subtasks([a.id])] == ["one", "two"]
    assert len(repo.list_subtasks([a.id, b.id])) == 3
    assert repo.set_subtask_done(s2.id, True).done is True
    assert repo.set_subtask_done(s2.id, False).done is False
    repo.archive_subtask(s1.id)
    assert [s.title for s in repo.list_subtasks([a.id])] == ["two"]


def test_subtasks_single_query(repo: SqliteRepository) -> None:
    tasks = [repo.add_task(f"t{i}") for i in range(5)]
    for t in tasks:
        repo.add_subtask(t.id, "s")
    statements: list[str] = []
    repo._conn.set_trace_callback(statements.append)
    repo.list_subtasks([t.id for t in tasks])
    repo._conn.set_trace_callback(None)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1


def test_subtasks_validation(repo: SqliteRepository) -> None:
    task = repo.add_task("A")
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(ValidationError):
            repo.add_subtask(task.id, bad)
    repo.add_subtask(task.id, "x" * 200)
    with pytest.raises(NotFoundError):
        repo.add_subtask("missing", "ok")
    with pytest.raises(NotFoundError):
        repo.set_subtask_done("missing", True)
    with pytest.raises(NotFoundError):
        repo.archive_subtask("missing")
    with pytest.raises(ValidationError):
        repo.list_subtasks("abc")  # type: ignore[arg-type]
    assert repo.list_subtasks([]) == []
    assert repo.list_subtasks(["nope"]) == []


# ---- expenses -------------------------------------------------------------------


def _exp(repo: SqliteRepository, day: date, desc: str = "Dinner", cents: int = 1000):
    return repo.add_expense(day, desc, cents, "nick")


def test_expenses_newest_first_and_since(repo: SqliteRepository) -> None:
    _exp(repo, date(2025, 1, 1), "old")
    _exp(repo, date(2025, 3, 1), "new")
    _exp(repo, date(2025, 2, 1), "mid")
    assert [e.description for e in repo.list_expenses()] == ["new", "mid", "old"]
    assert [e.description for e in repo.list_expenses(since=date(2025, 2, 1))] == ["new", "mid"]
    assert len(repo.list_expenses(limit=1)) == 1
    assert len(repo.list_expenses(limit=0)) == 1  # clamped up to 1


def test_expense_fields_and_archive(repo: SqliteRepository) -> None:
    e = repo.add_expense(date(2025, 1, 2), " Pizza ", 2500, "natalie", "other_only")
    assert (e.description, e.amount_cents, e.paid_by, e.split, e.kind) == (
        "Pizza", 2500, "natalie", "other_only", "expense",
    )  # fmt: skip
    assert e.created_by == "nick-id" and e.created_at.tzinfo is not None
    s = repo.add_expense(date(2025, 1, 3), "Settle up", 500, "nick", kind="settlement")
    assert s.kind == "settlement"
    repo.archive_expense(e.id)
    assert [x.id for x in repo.list_expenses()] == [s.id]
    with pytest.raises(NotFoundError):
        repo.archive_expense(e.id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"description": ""},
        {"description": "x" * 201},
        {"amount_cents": 0},
        {"amount_cents": -5},
        {"amount_cents": 100_000_001},
        {"amount_cents": 12.5},
        {"amount_cents": True},
        {"paid_by": "bob"},
        {"split": "thirds"},
        {"kind": "gift"},
        {"day": "2025-01-01"},
    ],
)
def test_expense_validation(repo: SqliteRepository, kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "day": date(2025, 1, 1), "description": "ok", "amount_cents": 100, "paid_by": "nick",
        "split": "equal", "kind": "expense",
    }  # fmt: skip
    with pytest.raises(ValidationError):
        repo.add_expense(**{**base, **kwargs})  # type: ignore[arg-type]
    assert repo.list_expenses() == []


def test_expense_max_amount_ok(repo: SqliteRepository) -> None:
    big = repo.add_expense(date(2025, 1, 1), "big", 100_000_000, "nick")
    assert big.amount_cents == 100_000_000


# ---- templates ------------------------------------------------------------------


def test_template_crud_and_filter(repo: SqliteRepository) -> None:
    t = repo.add_template("shopping", " Weekly ", "milk\n\n  eggs  \n")
    r = repo.add_template("recipe", "Pasta", "pasta\nsauce")
    assert t.name == "Weekly" and t.items == "milk\neggs"
    assert [x.name for x in repo.list_templates()] == ["Pasta", "Weekly"]
    assert [x.id for x in repo.list_templates("recipe")] == [r.id]
    assert repo.update_template(t.id, name="Big shop", items="a").name == "Big shop"
    assert repo.update_template(t.id).items == "a"
    repo.archive_template(r.id)
    assert [x.id for x in repo.list_templates("recipe")] == []
    with pytest.raises(NotFoundError):
        repo.update_template(r.id, name="zzz")
    with pytest.raises(NotFoundError):
        repo.archive_template("missing")


@pytest.mark.parametrize(
    ("kind", "name", "items"),
    [
        ("meal", "ok", ""),
        ("shopping", "", ""),
        ("shopping", "n" * 101, ""),
        ("shopping", "ok", "\n".join(f"i{i}" for i in range(61))),
        ("shopping", "ok", "x" * 201),
        ("shopping", "ok", "\n".join(["y" * 40] * 51)),  # >2000 chars
        ("shopping", "ok", 5),
    ],
)
def test_template_validation(repo: SqliteRepository, kind: str, name: str, items: object) -> None:
    with pytest.raises(ValidationError):
        repo.add_template(kind, name, items)  # type: ignore[arg-type]
    assert repo.list_templates() == []


def test_template_limits_boundary_ok(repo: SqliteRepository) -> None:
    repo.add_template("shopping", "n" * 100, "\n".join(f"i{i}" for i in range(60)))
    repo.add_template("shopping", "ok", "x" * 200)


def test_template_update_validates(repo: SqliteRepository) -> None:
    t = repo.add_template("shopping", "a", "b")
    with pytest.raises(ValidationError):
        repo.update_template(t.id, kind="recipe")
    with pytest.raises(ValidationError):
        repo.update_template(t.id, name="")


def test_template_to_grocery_dedupes(repo: SqliteRepository) -> None:
    repo.add_grocery("MILK")
    t = repo.add_template("shopping", "w", "milk\neggs\nEggs\nbread")
    assert repo.template_to_grocery(t.id) == 2
    assert sorted(g.name for g in repo.list_grocery()) == ["MILK", "bread", "eggs"]
    assert repo.template_to_grocery(t.id) == 0
    with pytest.raises(NotFoundError):
        repo.template_to_grocery("missing")


# ---- members & export -----------------------------------------------------------


def test_list_members(repo: SqliteRepository) -> None:
    assert repo.list_members() == {"nick": "nick", "natalie": "natalie"}


def test_export_includes_archived_and_iso_values(repo: SqliteRepository) -> None:
    t = repo.add_task("a", due_date=date(2025, 5, 6))
    repo.add_task("b")
    repo.archive_task(t.id)
    rows = repo.export_rows("tasks")
    assert len(rows) == 2
    row = next(r for r in rows if r["id"] == t.id)
    assert row["due_date"] == "2025-05-06"
    assert isinstance(row["created_at"], str) and row["archived_at"] is not None
    prims = (str, int, float, bool, type(None))
    assert all(isinstance(v, prims) for r in rows for v in r.values())


def test_export_every_whitelisted_table(repo: SqliteRepository) -> None:
    for table in EXPORT_TABLES:
        assert repo.export_rows(table) == [] or isinstance(repo.export_rows(table), list)


@pytest.mark.parametrize(
    "table", ["users", "sqlite_master", "tasks; DROP TABLE tasks", "", None, 5]
)
def test_export_rejects_other_tables(repo: SqliteRepository, table: object) -> None:
    with pytest.raises(ValidationError):
        repo.export_rows(table)  # type: ignore[arg-type]


def test_export_limit_clamped(repo: SqliteRepository) -> None:
    for i in range(3):
        repo.add_task(f"t{i}")
    assert len(repo.export_rows("tasks", limit=2)) == 2
    assert len(repo.export_rows("tasks", limit=0)) == 1
    assert len(repo.export_rows("tasks", limit=10**9)) == 3


# ---- no deletes -----------------------------------------------------------------


@pytest.mark.parametrize("table", ["subtasks", "expenses", "templates"])
def test_new_tables_reject_delete(repo: SqliteRepository, table: str) -> None:
    task = repo.add_task("t")
    repo.add_subtask(task.id, "s")
    repo.add_expense(date(2025, 1, 1), "e", 100, "nick")
    repo.add_template("shopping", "n", "i")
    with pytest.raises(sqlite3.DatabaseError):
        repo._conn.execute(f"DELETE FROM {table}")
