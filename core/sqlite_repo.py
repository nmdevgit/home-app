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
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from core import clock, rules
from core.errors import BackendError, NotFoundError, ValidationError
from core.repo import (
    DEFAULT_LIMIT,
    Activity,
    ArchivedItem,
    ArchivedKind,
    Assignee,
    Bill,
    BillRecurrence,
    EventItem,
    EventOccurrence,
    EventRecurrence,
    EventWho,
    Expense,
    ExpenseKind,
    ExpenseSplit,
    Goal,
    GoalMove,
    GroceryCategory,
    GroceryItem,
    Meal,
    MealSlot,
    Note,
    Person,
    Prefs,
    Priority,
    Recurrence,
    SearchHit,
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
    category TEXT NOT NULL DEFAULT 'other',
    price_cents INTEGER
        CHECK (price_cents IS NULL OR (price_cents >= 0 AND price_cents <= 100000000))
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
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id TEXT PRIMARY KEY,
    accent TEXT NOT NULL DEFAULT 'teal',
    pinned TEXT NOT NULL DEFAULT '',
    start_page TEXT NOT NULL DEFAULT 'today',
    compact INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    day TEXT NOT NULL,
    start_time TEXT,
    who TEXT NOT NULL DEFAULT 'both',
    notes TEXT NOT NULL DEFAULT '',
    recurrence TEXT NOT NULL DEFAULT 'none',
    remind_days INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    due_date TEXT,
    icon TEXT NOT NULL DEFAULT 'savings',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS goal_moves (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    person TEXT NOT NULL,
    day TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_day ON events (day);
CREATE INDEX IF NOT EXISTS idx_goal_moves_goal ON goal_moves (goal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks (task_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_expenses_day ON expenses (day);
CREATE INDEX IF NOT EXISTS idx_meals_day ON meals (day);
CREATE INDEX IF NOT EXISTS idx_bills_due ON bills (due_date);
CREATE INDEX IF NOT EXISTS idx_notes_order ON notes (pinned, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks (completed_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, archived_at);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (due_date);
CREATE INDEX IF NOT EXISTS idx_grocery_active ON grocery_items (archived_at, checked);
DROP TRIGGER IF EXISTS tasks_no_delete;
DROP TRIGGER IF EXISTS grocery_no_delete;
DROP TRIGGER IF EXISTS meals_no_delete;
DROP TRIGGER IF EXISTS bills_no_delete;
DROP TRIGGER IF EXISTS notes_no_delete;
DROP TRIGGER IF EXISTS subtasks_no_delete;
DROP TRIGGER IF EXISTS expenses_no_delete;
DROP TRIGGER IF EXISTS templates_no_delete;
"""

# Columns added after v1; older dev database files get them via ALTER TABLE.
_ADDED_COLUMNS = (
    ("tasks", "priority", "TEXT NOT NULL DEFAULT 'normal'"),
    ("tasks", "rotate", "INTEGER NOT NULL DEFAULT 0"),
    ("grocery_items", "category", "TEXT NOT NULL DEFAULT 'other'"),
    ("tasks", "completed_by", "TEXT"),
    (
        "grocery_items",
        "price_cents",
        "INTEGER CHECK (price_cents IS NULL OR (price_cents >= 0 AND price_cents <= 100000000))",
    ),
)
STORAGE_LIMIT_BYTES = 500 * 1024 * 1024

_TASK_COLUMNS = (
    "id, title, notes, assignee, due_date, recurrence, status, "
    "created_by, created_at, completed_at, priority, rotate, completed_by"
)
_GROCERY_COLUMNS = "id, name, quantity, checked, added_by, created_at, category, price_cents"
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
_EVENT_COLUMNS = (
    "id, title, day, start_time, who, notes, recurrence, remind_days, created_by, created_at"
)
_GOAL_COLUMNS = "id, name, target_cents, due_date, icon, created_by, created_at"
_MOVE_COLUMNS = "id, goal_id, amount_cents, person, day, note, created_at"
_SPAWN_SLACK = timedelta(seconds=60)


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
        price_cents=row["price_cents"],
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


def _row_to_event(row: sqlite3.Row) -> EventItem:
    return EventItem(
        id=row["id"],
        title=row["title"],
        day=date.fromisoformat(row["day"]),
        start_time=time.fromisoformat(row["start_time"]) if row["start_time"] else None,
        who=row["who"],
        notes=row["notes"],
        recurrence=row["recurrence"],
        remind_days=row["remind_days"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_goal(row: sqlite3.Row, saved: int) -> Goal:
    return Goal(
        id=row["id"],
        name=row["name"],
        target_cents=row["target_cents"],
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        icon=row["icon"],
        saved_cents=saved,
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_move(row: sqlite3.Row) -> GoalMove:
    return GoalMove(
        id=row["id"],
        goal_id=row["goal_id"],
        amount_cents=row["amount_cents"],
        person=row["person"],
        day=date.fromisoformat(row["day"]),
        note=row["note"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _like(text: str) -> str:
    """LIKE pattern for a sanitised query; the escape is belt and braces."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("since must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _time_db(value: object) -> str | None:
    return value.strftime("%H:%M") if isinstance(value, time) else None


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

    def set_grocery_price(self, item_id: str, price_cents: int | None) -> GroceryItem:
        cleaned = rules.clean_price_cents(price_cents)
        self._require_grocery(item_id)
        self._update("grocery_items", item_id, {"price_cents": cleaned})
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

    # ---- permanent delete ----------------------------------------------
    def delete_task(self, task_id: str) -> None:
        with self._conn:
            if not self._conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise NotFoundError(f"task {task_id} not found")
            self._conn.execute("DELETE FROM subtasks WHERE task_id = ?", (task_id,))
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def delete_subtask(self, subtask_id: str) -> None:
        self._delete("subtasks", subtask_id, "subtask")

    def delete_grocery(self, item_id: str) -> None:
        self._delete("grocery_items", item_id, "grocery item")

    def delete_checked_grocery(self) -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM grocery_items WHERE checked = 1 AND archived_at IS NULL"
            )
        return cur.rowcount

    def delete_meal(self, meal_id: str) -> None:
        self._delete("meals", meal_id, "meal")

    def delete_bill(self, bill_id: str) -> None:
        self._delete("bills", bill_id, "bill")

    def delete_note(self, note_id: str) -> None:
        self._delete("notes", note_id, "note")

    def delete_expense(self, expense_id: str) -> None:
        self._delete("expenses", expense_id, "expense")

    def delete_template(self, template_id: str) -> None:
        self._delete("templates", template_id, "template")

    def purge_archived(self) -> int:
        total = 0
        with self._conn:
            # children first: subtasks that are archived or belong to an archived task
            total += self._conn.execute(
                "DELETE FROM subtasks WHERE archived_at IS NOT NULL OR task_id IN "
                "(SELECT id FROM tasks WHERE archived_at IS NOT NULL)"
            ).rowcount
            total += self._conn.execute(
                "DELETE FROM goal_moves WHERE goal_id IN "
                "(SELECT id FROM goals WHERE archived_at IS NOT NULL)"
            ).rowcount
            for table in (
                "tasks", "grocery_items", "meals", "bills", "notes", "expenses", "templates",
                "events", "goals",
            ):
                total += self._conn.execute(
                    f"DELETE FROM {table} WHERE archived_at IS NOT NULL"
                ).rowcount
        return total

    # ---- round 4: activity, search ---------------------------------------
    def list_activity(self, since: datetime, limit: int = 50) -> list[Activity]:
        cut = _utc_iso(since)
        n = rules.clamp_limit(limit)
        members = self.list_members()
        out: list[Activity] = []

        def person(user_id: str | None) -> Person | None:
            return members.get(user_id) if user_id else None

        def add(sql: str, build: Callable[[sqlite3.Row], Activity]) -> None:
            out.extend(build(r) for r in self._conn.execute(sql, (cut, n)).fetchall())

        def when(value: str) -> datetime:
            return datetime.fromisoformat(value)

        add(
            "SELECT id, title, completed_at, completed_by FROM tasks WHERE archived_at IS NULL "
            "AND status = 'done' AND completed_at >= ? ORDER BY completed_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["completed_at"]), person(r["completed_by"]), "finished", "task",
                r["title"], r["id"],
            ),
        )
        add(
            "SELECT id, title, created_at, created_by FROM tasks WHERE archived_at IS NULL "
            "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["created_at"]), person(r["created_by"]), "added", "task",
                r["title"], r["id"],
            ),
        )
        add(
            "SELECT id, name, created_at, added_by FROM grocery_items WHERE archived_at IS NULL "
            "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["created_at"]), person(r["added_by"]), "added", "grocery",
                r["name"], r["id"],
            ),
        )
        add(
            "SELECT id, description, kind, created_at, created_by FROM expenses "
            "WHERE archived_at IS NULL AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["created_at"]), person(r["created_by"]),
                "settled" if r["kind"] == "settlement" else "paid", "expense",
                r["description"], r["id"],
            ),
        )
        add(
            "SELECT id, title, updated_at, created_by FROM notes WHERE archived_at IS NULL "
            "AND updated_at >= ? ORDER BY updated_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["updated_at"]), person(r["created_by"]), "updated", "note",
                r["title"], r["id"],
            ),
        )
        add(
            "SELECT m.id, m.amount_cents, m.person, m.created_at, g.name FROM goal_moves m "
            "JOIN goals g ON g.id = m.goal_id WHERE m.created_at >= ? "
            "ORDER BY m.created_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["created_at"]), r["person"],
                "saved to" if r["amount_cents"] > 0 else "withdrew from", "goal",
                r["name"], r["id"],
            ),
        )
        add(
            "SELECT id, title, created_at, created_by FROM events WHERE archived_at IS NULL "
            "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            lambda r: Activity(
                when(r["created_at"]), person(r["created_by"]), "added", "event",
                r["title"], r["id"],
            ),
        )
        out.sort(key=lambda a: a.at, reverse=True)
        return out[:n]

    def search(self, query: str, limit: int = 40) -> list[SearchHit]:
        pattern = _like(rules.sanitize_search(query))
        cap = rules.clamp_limit(limit)
        per = rules.SEARCH_PER_SOURCE
        # (kind, page, table, title column, snippet column, searched columns)
        sources = (
            ("task", "tasks", "tasks", "title", "notes", ("title", "notes")),
            ("grocery", "grocery", "grocery_items", "name", "quantity", ("name",)),
            ("note", "notes", "notes", "title", "body", ("title", "body")),
            ("meal", "meals", "meals", "title", "ingredients", ("title",)),
            ("template", "templates", "templates", "name", "items", ("name", "items")),
            ("bill", "bills", "bills", "name", "due_date", ("name",)),
            ("event", "calendar", "events", "title", "day", ("title",)),
            ("goal", "goals", "goals", "name", "''", ("name",)),
        )
        hits: list[SearchHit] = []
        for kind, page, table, title_col, snip_col, cols in sources:
            where = " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols)
            rows = self._conn.execute(
                f"SELECT id, {title_col} AS t, {snip_col} AS s FROM {table} "
                f"WHERE archived_at IS NULL AND ({where}) LIMIT ?",
                (*([pattern] * len(cols)), per),
            ).fetchall()
            for r in rows:
                snip = f"due {r['s']}" if kind == "bill" else rules.snippet(str(r["s"]))
                hits.append(SearchHit(kind, r["id"], r["t"], snip, page))
        return hits[:cap]

    # ---- round 4: bulk, undo, restores -------------------------------------
    def bulk_complete_tasks(self, task_ids: list[str]) -> int:
        count = 0
        for task_id in rules.clean_bulk_ids(task_ids):
            try:
                if self._require_task(task_id).status == "open":
                    self.complete_task(task_id)
                    count += 1
            except NotFoundError:
                continue
        return count

    def bulk_update_tasks(self, task_ids: list[str], **fields: object) -> int:
        cleaned = rules.validate_bulk_task_fields(fields)
        ids = rules.clean_bulk_ids(task_ids)
        if not ids:
            return 0
        assignments = ", ".join(f"{col} = ?" for col in cleaned)
        marks = ",".join("?" for _ in ids)
        with self._conn:
            cur = self._conn.execute(
                f"UPDATE tasks SET {assignments} WHERE archived_at IS NULL AND id IN ({marks})",
                (*[_db_value(v) for v in cleaned.values()], *ids),
            )
        return cur.rowcount

    def bulk_archive_tasks(self, task_ids: list[str]) -> int:
        ids = rules.clean_bulk_ids(task_ids)
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self._conn:
            cur = self._conn.execute(
                f"UPDATE tasks SET archived_at = ? WHERE archived_at IS NULL AND id IN ({marks})",
                (rules.utc_now().isoformat(), *ids),
            )
        return cur.rowcount

    def bulk_delete_tasks(self, task_ids: list[str]) -> int:
        ids = rules.clean_bulk_ids(task_ids)
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self._conn:
            self._conn.execute(f"DELETE FROM subtasks WHERE task_id IN ({marks})", ids)
            cur = self._conn.execute(f"DELETE FROM tasks WHERE id IN ({marks})", ids)
        return cur.rowcount

    def undo_complete(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.status == "done" and task.recurrence != "none" and task.completed_at:
            expected = rules.swap_assignee(task.assignee) if task.rotate else task.assignee
            row = self._conn.execute(
                "SELECT id FROM tasks WHERE archived_at IS NULL AND status = 'open' "
                "AND id != ? AND title = ? AND notes = ? AND recurrence = ? AND priority = ? "
                "AND rotate = ? AND assignee = ? AND created_at >= ? "
                "AND NOT EXISTS (SELECT 1 FROM subtasks s WHERE s.task_id = tasks.id) "
                "ORDER BY created_at DESC LIMIT 1",
                (
                    task_id, task.title, task.notes, task.recurrence, task.priority,
                    1 if task.rotate else 0, expected,
                    _utc_iso(task.completed_at - _SPAWN_SLACK),
                ),
            ).fetchone()
            if row is not None:
                with self._conn:
                    self._conn.execute("DELETE FROM tasks WHERE id = ?", (row["id"],))
        return self.reopen_task(task_id)

    def restore_meal(self, meal_id: str) -> Meal:
        self._restore("meals", meal_id, "meal")
        return self._require_meal(meal_id)

    def restore_bill(self, bill_id: str) -> Bill:
        self._restore("bills", bill_id, "bill")
        return self._require_bill(bill_id)

    def restore_note(self, note_id: str) -> Note:
        self._restore("notes", note_id, "note")
        return self._require_note(note_id)

    def restore_expense(self, expense_id: str) -> Expense:
        self._restore("expenses", expense_id, "expense")
        return self._require_expense(expense_id)

    def restore_template(self, template_id: str) -> Template:
        self._restore("templates", template_id, "template")
        return self._require_template(template_id)

    # ---- unified archive -----------------------------------------------------------
    def list_archived_items(self, limit: int = DEFAULT_LIMIT) -> list[ArchivedItem]:
        n = rules.clamp_limit(limit)
        items: list[ArchivedItem] = []
        for kind, (table, columns) in rules.ARCHIVED_SOURCES.items():
            rows = self._conn.execute(
                f"SELECT {columns} FROM {table} WHERE archived_at IS NOT NULL "
                "ORDER BY archived_at DESC LIMIT ?",
                (n,),
            ).fetchall()
            for row in rows:
                title, detail = rules.archived_title_detail(kind, row)
                archived = datetime.fromisoformat(row["archived_at"])
                items.append(ArchivedItem(kind, row["id"], title, detail, archived))  # type: ignore[arg-type]
        items.sort(key=lambda i: i.archived_at, reverse=True)
        return items

    def restore_item(self, kind: ArchivedKind, item_id: str) -> None:
        rules.check_archived_kind(kind)
        table = rules.ARCHIVED_SOURCES[kind][0]
        if kind == "subtask":
            row = self._conn.execute(
                "SELECT task_id FROM subtasks WHERE id = ? AND archived_at IS NOT NULL",
                (item_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"archived subtask {item_id} not found")
            parent = self._conn.execute(
                "SELECT 1 FROM tasks WHERE id = ? AND archived_at IS NULL", (row["task_id"],)
            ).fetchone()
            if parent is None:
                raise ValidationError(
                    "This subtask's task is archived or deleted - restore the task first."
                )
        self._restore(table, item_id, kind)

    # ---- events --------------------------------------------------------------
    def list_events(
        self, start: date, end: date, limit: int = DEFAULT_LIMIT
    ) -> list[EventOccurrence]:
        lo = rules.clean_required_date(start, "start")
        hi = rules.clean_required_date(end, "end")
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events WHERE archived_at IS NULL AND day <= ? "
            "AND (recurrence != 'none' OR day >= ?) ORDER BY day LIMIT ?",
            (hi.isoformat(), lo.isoformat(), rules.MAX_LIMIT),
        ).fetchall()
        return self._expand(_row_to_event(r) for r in rows)(lo, hi, limit)

    def upcoming_events(
        self, today: date, days: int = 60, limit: int = 10
    ) -> list[EventOccurrence]:
        first = rules.clean_required_date(today, "today")
        span = rules.clean_int_range(days, "days", 1, 366)
        return self.list_events(first, first + timedelta(days=span), limit)

    @staticmethod
    def _expand(events: Iterable[EventItem]) -> Callable[[date, date, int], list[EventOccurrence]]:
        def run(lo: date, hi: date, limit: int) -> list[EventOccurrence]:
            found = [
                EventOccurrence(ev, d)
                for ev in events
                for d in rules.event_occurrences(ev, lo, hi)
            ]
            found.sort(key=lambda o: (o.on, o.event.start_time or time.min, o.event.title))
            return found[: rules.clamp_limit(limit)]

        return run

    def add_event(
        self,
        title: str,
        day: date,
        who: EventWho = "both",
        start_time: time | None = None,
        notes: str = "",
        recurrence: EventRecurrence = "none",
        remind_days: int = 0,
    ) -> EventItem:
        c = rules.validate_event_fields(
            {
                "title": title, "day": day, "who": who, "start_time": start_time,
                "notes": notes, "recurrence": recurrence, "remind_days": remind_days,
            }
        )
        event_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO events (id, title, day, start_time, who, notes, recurrence, "
                "remind_days, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, c["title"], _db_value(c["day"]), _time_db(c["start_time"]),
                    c["who"], c["notes"], c["recurrence"], c["remind_days"], self._user_id,
                    rules.utc_now().isoformat(),
                ),
            )
        return self._require_event(event_id)

    def update_event(self, event_id: str, **fields: object) -> EventItem:
        cleaned = rules.validate_event_fields(fields)
        self._require_event(event_id)
        if "start_time" in cleaned:
            cleaned["start_time"] = _time_db(cleaned["start_time"])
        self._update("events", event_id, cleaned)
        return self._require_event(event_id)

    def archive_event(self, event_id: str) -> None:
        self._require_event(event_id)
        self._archive("events", event_id)

    def restore_event(self, event_id: str) -> EventItem:
        self._restore("events", event_id, "event")
        return self._require_event(event_id)

    def delete_event(self, event_id: str) -> None:
        self._delete("events", event_id, "event")

    # ---- goals -------------------------------------------------------------------
    def list_goals(self, limit: int = 50) -> list[Goal]:
        rows = self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE archived_at IS NULL "
            "ORDER BY created_at, rowid LIMIT ?",
            (rules.clamp_limit(limit),),
        ).fetchall()
        return [_row_to_goal(r, self._saved(r["id"])) for r in rows]

    def add_goal(
        self, name: str, target_cents: int, due_date: date | None = None, icon: str = "savings"
    ) -> Goal:
        c = rules.validate_goal_fields(
            {"name": name, "target_cents": target_cents, "due_date": due_date, "icon": icon}
        )
        goal_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO goals (id, name, target_cents, due_date, icon, created_by, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    goal_id, c["name"], c["target_cents"], _db_value(c["due_date"]), c["icon"],
                    self._user_id, rules.utc_now().isoformat(),
                ),
            )
        return self._require_goal(goal_id)

    def update_goal(self, goal_id: str, **fields: object) -> Goal:
        cleaned = rules.validate_goal_fields(fields)
        self._require_goal(goal_id)
        self._update("goals", goal_id, cleaned)
        return self._require_goal(goal_id)

    def archive_goal(self, goal_id: str) -> None:
        self._require_goal(goal_id)
        self._archive("goals", goal_id)

    def delete_goal(self, goal_id: str) -> None:
        with self._conn:
            if not self._conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone():
                raise NotFoundError(f"goal {goal_id} not found")
            self._conn.execute("DELETE FROM goal_moves WHERE goal_id = ?", (goal_id,))
            self._conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    def add_goal_move(
        self, goal_id: str, amount_cents: int, person: Person, note: str = ""
    ) -> GoalMove:
        c = rules.validate_goal_move(amount_cents, person, note)
        self._require_goal(goal_id)
        move_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO goal_moves (id, goal_id, amount_cents, person, day, note, "
                "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    move_id, goal_id, c["amount_cents"], c["person"], clock.today().isoformat(),
                    c["note"], self._user_id, rules.utc_now().isoformat(),
                ),
            )
        return self._require_move(move_id)

    def list_goal_moves(self, goal_id: str, limit: int = 50) -> list[GoalMove]:
        rows = self._conn.execute(
            f"SELECT {_MOVE_COLUMNS} FROM goal_moves WHERE goal_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (goal_id, rules.clamp_limit(limit)),
        ).fetchall()
        return [_row_to_move(r) for r in rows]

    def delete_goal_move(self, move_id: str) -> None:
        self._delete("goal_moves", move_id, "goal move")

    def _saved(self, goal_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM goal_moves WHERE goal_id = ?",
            (goal_id,),
        ).fetchone()
        return int(row["s"])

    # ---- prefs ---------------------------------------------------------------------
    def get_prefs(self) -> Prefs:
        row = self._conn.execute(
            "SELECT accent, pinned, start_page, compact FROM user_prefs WHERE user_id = ?",
            (self._user_id,),
        ).fetchone()
        if row is None:
            return Prefs()
        return Prefs(
            accent=row["accent"],
            pinned=rules.parse_pinned(row["pinned"]),
            start_page=row["start_page"],
            compact=bool(row["compact"]),
        )

    def save_prefs(self, **fields: object) -> Prefs:
        cleaned = rules.validate_prefs(fields)
        current = self.get_prefs()
        merged = {
            "accent": current.accent,
            "pinned": current.pinned,
            "start_page": current.start_page,
            "compact": current.compact,
            **cleaned,
        }
        with self._conn:
            self._conn.execute(
                "INSERT INTO user_prefs (user_id, accent, pinned, start_page, compact, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET "
                "accent = excluded.accent, pinned = excluded.pinned, "
                "start_page = excluded.start_page, compact = excluded.compact, "
                "updated_at = excluded.updated_at",
                (
                    self._user_id, merged["accent"], ",".join(merged["pinned"]),  # type: ignore[arg-type]
                    merged["start_page"], 1 if merged["compact"] else 0,
                    rules.utc_now().isoformat(),
                ),
            )
        return self.get_prefs()

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

    def _delete(self, table: str, row_id: str, label: str) -> None:
        """Permanently deletes one row (active or archived); NotFoundError if absent."""
        with self._conn:
            cur = self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        if cur.rowcount == 0:
            raise NotFoundError(f"{label} {row_id} not found")

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

    def _require_event(self, event_id: str) -> EventItem:
        row = self._fetch("events", _EVENT_COLUMNS, event_id)
        if row is None:
            raise NotFoundError(f"event {event_id} not found")
        return _row_to_event(row)

    def _require_goal(self, goal_id: str) -> Goal:
        row = self._fetch("goals", _GOAL_COLUMNS, goal_id)
        if row is None:
            raise NotFoundError(f"goal {goal_id} not found")
        return _row_to_goal(row, self._saved(goal_id))

    def _require_move(self, move_id: str) -> GoalMove:
        row = self._conn.execute(
            f"SELECT {_MOVE_COLUMNS} FROM goal_moves WHERE id = ?", (move_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"goal move {move_id} not found")
        return _row_to_move(row)

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
