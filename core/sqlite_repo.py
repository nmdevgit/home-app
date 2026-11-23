"""SQLite implementation of the Repository protocol (dev and tests).

Mirrors the Supabase schema, including the no-delete guarantee.
"""
# ruff: noqa: S608
# S608: f-strings only splice module-constant column lists / allow-listed names;
# every value is bound with "?".
from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from core import clock, rules
from core.errors import BackendError, NotFoundError, ValidationError
from core.repo import (
    DEFAULT_LIMIT,
    Assignee,
    Bill,
    BillRecurrence,
    Expense,
    ExpenseKind,
    ExpenseSplit,
    GroceryCategory,
    GroceryItem,
    Meal,
    MealSlot,
    Note,
    Person,
    Priority,
    Recurrence,
    StorageUsage,
    Subtask,
    Task,
    Template,
    TemplateKind,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    assignee TEXT NOT NULL DEFAULT 'either',
    due_date TEXT,
    recurrence TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'open',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    archived_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    rotate INTEGER NOT NULL DEFAULT 0,
    completed_by TEXT
);
CREATE TABLE IF NOT EXISTS grocery_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    quantity TEXT NOT NULL DEFAULT '',
    checked INTEGER NOT NULL DEFAULT 0,
    added_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    category TEXT NOT NULL DEFAULT 'other'
);
CREATE TABLE IF NOT EXISTS meals (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'dinner',
    title TEXT NOT NULL,
    ingredients TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS bills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'monthly',
    last_paid_on TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS subtasks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks (id),
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS expenses (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    paid_by TEXT NOT NULL,
    split TEXT NOT NULL DEFAULT 'equal',
    kind TEXT NOT NULL DEFAULT 'expense',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    items TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks (task_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_expenses_day ON expenses (day);
CREATE INDEX IF NOT EXISTS idx_meals_day ON meals (day);
CREATE INDEX IF NOT EXISTS idx_bills_due ON bills (due_date);
CREATE INDEX IF NOT EXISTS idx_notes_order ON notes (pinned, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks (completed_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, archived_at);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (due_date);
CREATE INDEX IF NOT EXISTS idx_grocery_active ON grocery_items (archived_at, checked);
CREATE TRIGGER IF NOT EXISTS tasks_no_delete BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS grocery_no_delete BEFORE DELETE ON grocery_items
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS meals_no_delete BEFORE DELETE ON meals
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS bills_no_delete BEFORE DELETE ON bills
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS notes_no_delete BEFORE DELETE ON notes
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS subtasks_no_delete BEFORE DELETE ON subtasks
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS expenses_no_delete BEFORE DELETE ON expenses
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS templates_no_delete BEFORE DELETE ON templates
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
"""

# Columns added after v1; older dev database files get them via ALTER TABLE.
_ADDED_COLUMNS = (
    ("tasks", "priority", "TEXT NOT NULL DEFAULT 'normal'"),
    ("tasks", "rotate", "INTEGER NOT NULL DEFAULT 0"),
    ("grocery_items", "category", "TEXT NOT NULL DEFAULT 'other'"),
    ("tasks", "completed_by", "TEXT"),
)
STORAGE_LIMIT_BYTES = 500 * 1024 * 1024

_TASK_COLUMNS = (
    "id, title, notes, assignee, due_date, recurrence, status, "
    "created_by, created_at, completed_at, priority, rotate, completed_by"
)
_GROCERY_COLUMNS = "id, name, quantity, checked, added_by, created_at, category"
_MEAL_COLUMNS = "id, day, slot, title, ingredients, created_by, created_at"
_BILL_COLUMNS = (
    "id, name, amount_cents, due_date, recurrence, last_paid_on, created_by, created_at"
)
_NOTE_COLUMNS = "id, title, body, pinned, created_by, created_at, updated_at"
_SUBTASK_COLUMNS = "id, task_id, title, done, created_at"
_EXPENSE_COLUMNS = (
    "id, day, description, amount_cents, paid_by, split, kind, created_by, created_at"
)
_TEMPLATE_COLUMNS = "id, kind, name, items, created_by, created_at"


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        notes=row["notes"],
        assignee=row["assignee"],
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        recurrence=row["recurrence"],
        status=row["status"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=(
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
        ),
        priority=row["priority"],
        rotate=bool(row["rotate"]),
        completed_by=row["completed_by"],
    )


def _row_to_grocery(row: sqlite3.Row) -> GroceryItem:
    return GroceryItem(
        id=row["id"],
        name=row["name"],
        quantity=row["quantity"],
        checked=bool(row["checked"]),
        added_by=row["added_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        category=row["category"],
    )


def _row_to_meal(row: sqlite3.Row) -> Meal:
    return Meal(
        id=row["id"],
        day=date.fromisoformat(row["day"]),
        slot=row["slot"],
        title=row["title"],
        ingredients=row["ingredients"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_bill(row: sqlite3.Row) -> Bill:
    return Bill(
        id=row["id"],
        name=row["name"],
        amount_cents=row["amount_cents"],
        due_date=date.fromisoformat(row["due_date"]),
        recurrence=row["recurrence"],
        last_paid_on=date.fromisoformat(row["last_paid_on"]) if row["last_paid_on"] else None,
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_note(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        pinned=bool(row["pinned"]),
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_subtask(row: sqlite3.Row) -> Subtask:
    return Subtask(
        id=row["id"],
        task_id=row["task_id"],
        title=row["title"],
        done=bool(row["done"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_expense(row: sqlite3.Row) -> Expense:
    return Expense(
        id=row["id"],
        day=date.fromisoformat(row["day"]),
        description=row["description"],
        amount_cents=row["amount_cents"],
        paid_by=row["paid_by"],
        split=row["split"],
        kind=row["kind"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_template(row: sqlite3.Row) -> Template:
    return Template(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        items=row["items"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("since must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _db_value(value: object) -> object:
    return value.isoformat() if isinstance(value, date) else value


class SqliteRepository:
    def __init__(self, path: str | Path = ":memory:", user_id: str = "local") -> None:
        self._user_id = user_id
        self._path = None if str(path) == ":memory:" else Path(path)
        target = path if str(path) == ":memory:" else str(Path(path))
        try:
            # Streamlit runs scripts on worker threads, so allow cross-thread use.
            self._conn = sqlite3.connect(target, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._add_missing_columns()
        except sqlite3.Error as exc:
            logger.exception("could not open sqlite database")
            raise BackendError("could not open database") from exc

    def _add_missing_columns(self) -> None:
        for table, column, ddl in _ADDED_COLUMNS:
            have = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self._conn.commit()

    # ---- tasks -------------------------------------------------------
    def list_tasks(
        self, include_done: bool = False, limit: int = DEFAULT_LIMIT
    ) -> list[Task]:
        sql = f"SELECT {_TASK_COLUMNS} FROM tasks WHERE archived_at IS NULL"
        if not include_done:
            sql += " AND status = 'open'"
        # NULL due dates sort last so dated chores surface first.
        sql += " ORDER BY due_date IS NULL, due_date, created_at LIMIT ?"
        rows = self._conn.execute(sql, (rules.clamp_limit(limit),)).fetchall()
        return [_row_to_task(r) for r in rows]

    def list_done_tasks(self, since: datetime, limit: int = DEFAULT_LIMIT) -> list[Task]:
        rows = self._conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM tasks WHERE archived_at IS NULL "
            "AND status = 'done' AND completed_at >= ? "
            "ORDER BY completed_at DESC, rowid DESC LIMIT ?",
            (_utc_iso(since), rules.clamp_limit(limit)),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def add_task(
        self,
        title: str,
        assignee: Assignee = "either",
        due_date: date | None = None,
        recurrence: Recurrence = "none",
        notes: str = "",
        priority: Priority = "normal",
        rotate: bool = False,
    ) -> Task:
        cleaned = rules.validate_task_fields(
            {
                "title": title,
                "assignee": assignee,
                "due_date": due_date,
                "recurrence": recurrence,
                "notes": notes,
                "priority": priority,
                "rotate": rotate,
            }
        )
        with self._conn:  # one transaction; _insert_task must not commit itself
            return self._insert_task(cleaned)

    def update_task(self, task_id: str, **fields: object) -> Task:
        cleaned = rules.validate_task_fields(fields)
        self._require_task(task_id)
        self._update("tasks", task_id, cleaned)
        return self._require_task(task_id)

    def complete_task(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.status == "done":
            return task  # idempotent: a double click must not spawn two occurrences
        now = rules.utc_now().isoformat()
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'done', completed_at = ?, completed_by = ? "
                "WHERE id = ?",
                (now, self._user_id, task_id),
            )
            if task.recurrence != "none":
                self._insert_task(
                    {
                        "title": task.title,
                        "notes": task.notes,
                        "assignee": (
                            rules.swap_assignee(task.assignee) if task.rotate else task.assignee
                        ),
                        "due_date": rules.next_due_date(task.due_date, task.recurrence),
                        "recurrence": task.recurrence,
                        "priority": task.priority,
                        "rotate": task.rotate,
                    }
                )
        return self._require_task(task_id)

    def reopen_task(self, task_id: str) -> Task:
        self._require_task(task_id)
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'open', completed_at = NULL, completed_by = NULL "
                "WHERE id = ?",
                (task_id,),
            )
        return self._require_task(task_id)

    def archive_task(self, task_id: str) -> None:
        self._require_task(task_id)
        self._archive("tasks", task_id)

    def list_archived_tasks(self, limit: int = DEFAULT_LIMIT) -> list[Task]:
        rows = self._conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM tasks WHERE archived_at IS NOT NULL "
            "ORDER BY archived_at DESC LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def restore_task(self, task_id: str) -> Task:
        self._restore("tasks", task_id, "task")
        return self._require_task(task_id)

    # ---- grocery -----------------------------------------------------
    def list_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]:
        rows = self._conn.execute(
            f"SELECT {_GROCERY_COLUMNS} FROM grocery_items "
            "WHERE archived_at IS NULL ORDER BY checked, created_at LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_grocery(r) for r in rows]

    def add_grocery(
        self, name: str, quantity: str = "", category: GroceryCategory = "other"
    ) -> GroceryItem:
        cleaned = rules.validate_grocery_fields(
            {"name": name, "quantity": quantity, "category": category}
        )
        return self._insert_grocery(cleaned)

    def update_grocery(self, item_id: str, **fields: object) -> GroceryItem:
        cleaned = rules.validate_grocery_fields(fields)
        self._require_grocery(item_id)
        self._update("grocery_items", item_id, cleaned)
        return self._require_grocery(item_id)

    def set_grocery_checked(self, item_id: str, checked: bool) -> GroceryItem:
        self._require_grocery(item_id)
        with self._conn:
            self._conn.execute(
                "UPDATE grocery_items SET checked = ? WHERE id = ?",
                (1 if checked else 0, item_id),
            )
        return self._require_grocery(item_id)

    def archive_checked_grocery(self) -> int:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE grocery_items SET archived_at = ? "
                "WHERE checked = 1 AND archived_at IS NULL",
                (rules.utc_now().isoformat(),),
            )
        return cur.rowcount

    def list_archived_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]:
        rows = self._conn.execute(
            f"SELECT {_GROCERY_COLUMNS} FROM grocery_items WHERE archived_at IS NOT NULL "
            "ORDER BY archived_at DESC LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_grocery(r) for r in rows]

    def restore_grocery(self, item_id: str) -> GroceryItem:
        self._restore("grocery_items", item_id, "grocery item")
        return self._require_grocery(item_id)

    def frequent_grocery(self, limit: int = 12) -> list[tuple[str, GroceryCategory]]:
        rows = self._conn.execute(
            "SELECT name, category FROM grocery_items "
            "ORDER BY created_at DESC, rowid DESC LIMIT 500"
        ).fetchall()
        pairs = [(r["name"], r["category"]) for r in rows]
        return rules.frequent_names(pairs, limit)  # type: ignore[return-value]

    # ---- meals -------------------------------------------------------
    def list_meals(self, start: date, end: date, limit: int = DEFAULT_LIMIT) -> list[Meal]:
        rows = self._conn.execute(
            f"SELECT {_MEAL_COLUMNS} FROM meals WHERE archived_at IS NULL "
            "AND day >= ? AND day <= ? ORDER BY day, created_at LIMIT ?",
            (
                rules.clean_required_date(start, "start").isoformat(),
                rules.clean_required_date(end, "end").isoformat(),
                rules.clamp_limit(limit),
            ),
        ).fetchall()
        meals = [_row_to_meal(r) for r in rows]
        return sorted(meals, key=lambda m: (m.day, rules.SLOT_ORDER[m.slot]))

    def add_meal(
        self, day: date, title: str, ingredients: str = "", slot: MealSlot = "dinner"
    ) -> Meal:
        cleaned = rules.validate_meal_fields(
            {"day": day, "title": title, "ingredients": ingredients, "slot": slot}
        )
        meal_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO meals (id, day, slot, title, ingredients, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    meal_id,
                    _db_value(cleaned["day"]),
                    cleaned["slot"],
                    cleaned["title"],
                    cleaned["ingredients"],
                    self._user_id,
                    rules.utc_now().isoformat(),
                ),
            )
        return self._require_meal(meal_id)

    def update_meal(self, meal_id: str, **fields: object) -> Meal:
        cleaned = rules.validate_meal_fields(fields)
        self._require_meal(meal_id)
        self._update("meals", meal_id, cleaned)
        return self._require_meal(meal_id)

    def archive_meal(self, meal_id: str) -> None:
        self._require_meal(meal_id)
        self._archive("meals", meal_id)

    def meal_to_grocery(self, meal_id: str) -> int:
        meal = self._require_meal(meal_id)
        rows = self._conn.execute(
            "SELECT name FROM grocery_items WHERE archived_at IS NULL"
        ).fetchall()
        seen = {r["name"].casefold() for r in rows}
        added = 0
        with self._conn:
            for line in meal.ingredients.splitlines():
                name = line.strip()
                if not name or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                self._insert_grocery({"name": name, "quantity": "", "category": "other"})
                added += 1
        return added

    # ---- bills -------------------------------------------------------
    def list_bills(self, limit: int = DEFAULT_LIMIT) -> list[Bill]:
        rows = self._conn.execute(
            f"SELECT {_BILL_COLUMNS} FROM bills WHERE archived_at IS NULL "
            "ORDER BY due_date, name LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_bill(r) for r in rows]

    def add_bill(
        self,
        name: str,
        amount_cents: int,
        due_date: date,
        recurrence: BillRecurrence = "monthly",
    ) -> Bill:
        cleaned = rules.validate_bill_fields(
            {
                "name": name,
                "amount_cents": amount_cents,
                "due_date": due_date,
                "recurrence": recurrence,
            }
        )
        bill_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO bills (id, name, amount_cents, due_date, recurrence, "
                "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    bill_id,
                    cleaned["name"],
                    cleaned["amount_cents"],
                    _db_value(cleaned["due_date"]),
                    cleaned["recurrence"],
                    self._user_id,
                    rules.utc_now().isoformat(),
                ),
            )
        return self._require_bill(bill_id)

    def update_bill(self, bill_id: str, **fields: object) -> Bill:
        cleaned = rules.validate_bill_fields(fields)
        self._require_bill(bill_id)
        self._update("bills", bill_id, cleaned)
        return self._require_bill(bill_id)

    def mark_bill_paid(self, bill_id: str) -> Bill:
        bill = self._require_bill(bill_id)
        today = clock.today()
        new_due = rules.next_bill_due(bill.due_date, bill.recurrence, today)
        self._update("bills", bill_id, {"last_paid_on": today, "due_date": new_due})
        return self._require_bill(bill_id)

    def archive_bill(self, bill_id: str) -> None:
        self._require_bill(bill_id)
        self._archive("bills", bill_id)

    # ---- notes -------------------------------------------------------
    def list_notes(self, limit: int = DEFAULT_LIMIT) -> list[Note]:
        rows = self._conn.execute(
            f"SELECT {_NOTE_COLUMNS} FROM notes WHERE archived_at IS NULL "
            "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_note(r) for r in rows]

    def add_note(self, title: str, body: str = "", pinned: bool = False) -> Note:
        cleaned = rules.validate_note_fields({"title": title, "body": body, "pinned": pinned})
        note_id = str(uuid.uuid4())
        now = rules.utc_now().isoformat()
        with self._conn:
            self._conn.execute(
                "INSERT INTO notes (id, title, body, pinned, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    cleaned["title"],
                    cleaned["body"],
                    1 if cleaned["pinned"] else 0,
                    self._user_id,
                    now,
                    now,
                ),
            )
        return self._require_note(note_id)

    def update_note(self, note_id: str, **fields: object) -> Note:
        cleaned = rules.validate_note_fields(fields)
        self._require_note(note_id)
        if cleaned:
            self._update("notes", note_id, {**cleaned, "updated_at": rules.utc_now().isoformat()})
        return self._require_note(note_id)

    def archive_note(self, note_id: str) -> None:
        self._require_note(note_id)
        self._archive("notes", note_id)

    # ---- subtasks ----------------------------------------------------
    def list_subtasks(self, task_ids: list[str]) -> list[Subtask]:
        ids = rules.clean_task_ids(task_ids)
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT {_SUBTASK_COLUMNS} FROM subtasks WHERE archived_at IS NULL "
            f"AND task_id IN ({marks}) ORDER BY created_at, rowid LIMIT ?",
            (*ids, rules.MAX_SUBTASKS),
        ).fetchall()
        return [_row_to_subtask(r) for r in rows]

    def add_subtask(self, task_id: str, title: str) -> Subtask:
        clean = rules.clean_subtask_title(title)
        self._require_task(task_id)
        sub_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO subtasks (id, task_id, title, done, created_by, created_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (sub_id, task_id, clean, self._user_id, rules.utc_now().isoformat()),
            )
        return self._require_subtask(sub_id)

    def set_subtask_done(self, subtask_id: str, done: bool) -> Subtask:
        self._require_subtask(subtask_id)
        self._update("subtasks", subtask_id, {"done": 1 if rules.clean_bool(done, "done") else 0})
        return self._require_subtask(subtask_id)

    def archive_subtask(self, subtask_id: str) -> None:
        self._require_subtask(subtask_id)
        self._archive("subtasks", subtask_id)

    # ---- expenses ----------------------------------------------------
    def list_expenses(self, since: date | None = None, limit: int = DEFAULT_LIMIT) -> list[Expense]:
        sql = f"SELECT {_EXPENSE_COLUMNS} FROM expenses WHERE archived_at IS NULL"
        params: list[object] = []
        if since is not None:
            sql += " AND day >= ?"
            params.append(rules.clean_required_date(since, "since").isoformat())
        sql += " ORDER BY day DESC, created_at DESC, rowid DESC LIMIT ?"
        params.append(rules.clamp_limit(limit))
        return [_row_to_expense(r) for r in self._conn.execute(sql, params).fetchall()]

    def add_expense(
        self,
        day: date,
        description: str,
        amount_cents: int,
        paid_by: Person,
        split: ExpenseSplit = "equal",
        kind: ExpenseKind = "expense",
    ) -> Expense:
        c = rules.validate_expense(day, description, amount_cents, paid_by, split, kind)
        exp_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO expenses (id, day, description, amount_cents, paid_by, split, "
                "kind, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exp_id,
                    _db_value(c["day"]),
                    c["description"],
                    c["amount_cents"],
                    c["paid_by"],
                    c["split"],
                    c["kind"],
                    self._user_id,
                    rules.utc_now().isoformat(),
                ),
            )
        return self._require_expense(exp_id)

    def archive_expense(self, expense_id: str) -> None:
        self._require_expense(expense_id)
        self._archive("expenses", expense_id)

    # ---- templates ---------------------------------------------------
    def list_templates(
        self, kind: TemplateKind | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Template]:
        sql = f"SELECT {_TEMPLATE_COLUMNS} FROM templates WHERE archived_at IS NULL"
        params: list[object] = []
        if kind is not None:
            sql += " AND kind = ?"
            params.append(rules.clean_choice(kind, "kind", rules.TEMPLATE_KINDS))
        sql += " ORDER BY name COLLATE NOCASE, created_at LIMIT ?"
        params.append(rules.clamp_limit(limit))
        return [_row_to_template(r) for r in self._conn.execute(sql, params).fetchall()]

    def add_template(self, kind: TemplateKind, name: str, items: str) -> Template:
        clean_kind = rules.clean_choice(kind, "kind", rules.TEMPLATE_KINDS)
        cleaned = rules.validate_template_fields({"name": name, "items": items})
        tpl_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO templates (id, kind, name, items, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    tpl_id,
                    clean_kind,
                    cleaned["name"],
                    cleaned["items"],
                    self._user_id,
                    rules.utc_now().isoformat(),
                ),
            )
        return self._require_template(tpl_id)

    def update_template(self, template_id: str, **fields: object) -> Template:
        cleaned = rules.validate_template_fields(fields)
        self._require_template(template_id)
        self._update("templates", template_id, cleaned)
        return self._require_template(template_id)

    def archive_template(self, template_id: str) -> None:
        self._require_template(template_id)
        self._archive("templates", template_id)

    def template_to_grocery(self, template_id: str) -> int:
        tpl = self._require_template(template_id)
        rows = self._conn.execute(
            "SELECT name FROM grocery_items WHERE archived_at IS NULL"
        ).fetchall()
        seen = {r["name"].casefold() for r in rows}
        added = 0
        with self._conn:
            for line in tpl.items.splitlines():
                name = line.strip()
                if not name or name.casefold() in seen:
                    continue
                seen.add(name.casefold())
                self._insert_grocery({"name": name, "quantity": "", "category": "other"})
                added += 1
        return added

    # ---- people & export ---------------------------------------------
    def list_members(self) -> dict[str, Person]:
        return {"nick": "nick", "natalie": "natalie"}

    def export_rows(self, table: str, limit: int = 5000) -> list[dict[str, object]]:
        name = rules.clean_export_table(table)  # allow-listed, safe to splice
        rows = self._conn.execute(
            f"SELECT * FROM {name} ORDER BY created_at, rowid LIMIT ?",
            (rules.clamp_export_limit(limit),),
        ).fetchall()
        return [{k: rules.export_value(row[k]) for k in row.keys()} for row in rows]

    # ---- storage meter -----------------------------------------------
    def storage_usage(self) -> StorageUsage:
        try:
            if self._path is not None:
                used = os.stat(self._path).st_size
            else:  # :memory: has no file; estimate from allocated pages
                pages = self._conn.execute("PRAGMA page_count").fetchone()[0]
                size = self._conn.execute("PRAGMA page_size").fetchone()[0]
                used = int(pages) * int(size)
        except (OSError, sqlite3.Error) as exc:
            logger.exception("could not measure sqlite size")
            raise BackendError("could not measure storage") from exc
        return StorageUsage(used_bytes=used, limit_bytes=STORAGE_LIMIT_BYTES)

    # ---- helpers -----------------------------------------------------
    def _update(self, table: str, row_id: str, values: dict[str, object]) -> None:
        """`table` is a module-internal constant; column names come from the
        validated allow-lists, never from caller input."""
        if not values:
            return
        assignments = ", ".join(f"{col} = ?" for col in values)
        params = [_db_value(v) for v in values.values()]
        with self._conn:
            self._conn.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?", (*params, row_id)
            )

    def _archive(self, table: str, row_id: str) -> None:
        self._update(table, row_id, {"archived_at": rules.utc_now().isoformat()})

    def _restore(self, table: str, row_id: str, label: str) -> None:
        with self._conn:
            cur = self._conn.execute(
                f"UPDATE {table} SET archived_at = NULL "
                "WHERE id = ? AND archived_at IS NOT NULL",
                (row_id,),
            )
        if cur.rowcount == 0:
            raise NotFoundError(f"archived {label} {row_id} not found")

    def _insert_task(self, values: dict[str, object]) -> Task:
        task_id = str(uuid.uuid4())
        due = values.get("due_date")
        self._conn.execute(
            "INSERT INTO tasks (id, title, notes, assignee, due_date, recurrence, "
            "status, created_by, created_at, priority, rotate) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
            (
                task_id,
                values["title"],
                values.get("notes", ""),
                values.get("assignee", "either"),
                due.isoformat() if isinstance(due, date) else None,
                values.get("recurrence", "none"),
                self._user_id,
                rules.utc_now().isoformat(),
                values.get("priority", "normal"),
                1 if values.get("rotate") else 0,
            ),
        )
        return self._require_task(task_id)

    def _insert_grocery(self, values: dict[str, object]) -> GroceryItem:
        item_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO grocery_items (id, name, quantity, checked, added_by, "
                "created_at, category) VALUES (?, ?, ?, 0, ?, ?, ?)",
                (
                    item_id,
                    values["name"],
                    values.get("quantity", ""),
                    self._user_id,
                    rules.utc_now().isoformat(),
                    values.get("category", "other"),
                ),
            )
        return self._require_grocery(item_id)

    def _require_task(self, task_id: str) -> Task:
        row = self._fetch("tasks", _TASK_COLUMNS, task_id)
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return _row_to_task(row)

    def _require_grocery(self, item_id: str) -> GroceryItem:
        row = self._fetch("grocery_items", _GROCERY_COLUMNS, item_id)
        if row is None:
            raise NotFoundError(f"grocery item {item_id} not found")
        return _row_to_grocery(row)

    def _require_meal(self, meal_id: str) -> Meal:
        row = self._fetch("meals", _MEAL_COLUMNS, meal_id)
        if row is None:
            raise NotFoundError(f"meal {meal_id} not found")
        return _row_to_meal(row)

    def _require_bill(self, bill_id: str) -> Bill:
        row = self._fetch("bills", _BILL_COLUMNS, bill_id)
        if row is None:
            raise NotFoundError(f"bill {bill_id} not found")
        return _row_to_bill(row)

    def _require_note(self, note_id: str) -> Note:
        row = self._fetch("notes", _NOTE_COLUMNS, note_id)
        if row is None:
            raise NotFoundError(f"note {note_id} not found")
        return _row_to_note(row)

    def _require_subtask(self, subtask_id: str) -> Subtask:
        row = self._fetch("subtasks", _SUBTASK_COLUMNS, subtask_id)
        if row is None:
            raise NotFoundError(f"subtask {subtask_id} not found")
        return _row_to_subtask(row)

    def _require_expense(self, expense_id: str) -> Expense:
        row = self._fetch("expenses", _EXPENSE_COLUMNS, expense_id)
        if row is None:
            raise NotFoundError(f"expense {expense_id} not found")
        return _row_to_expense(row)

    def _require_template(self, template_id: str) -> Template:
        row = self._fetch("templates", _TEMPLATE_COLUMNS, template_id)
        if row is None:
            raise NotFoundError(f"template {template_id} not found")
        return _row_to_template(row)

    def _fetch(self, table: str, columns: str, row_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            f"SELECT {columns} FROM {table} WHERE id = ? AND archived_at IS NULL",
            (row_id,),
        ).fetchone()
