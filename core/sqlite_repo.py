"""SQLite implementation of the Repository protocol (dev and tests).

Mirrors the Supabase schema, including the no-delete guarantee.
"""
# ruff: noqa: S608
# S608: f-strings only splice module-constant column lists / allow-listed names;
# every value is bound with "?".
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

from core import rules
from core.errors import BackendError, NotFoundError
from core.repo import Assignee, GroceryItem, Recurrence, Task

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
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS grocery_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    quantity TEXT NOT NULL DEFAULT '',
    checked INTEGER NOT NULL DEFAULT 0,
    added_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, archived_at);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (due_date);
CREATE INDEX IF NOT EXISTS idx_grocery_active ON grocery_items (archived_at, checked);
CREATE TRIGGER IF NOT EXISTS tasks_no_delete BEFORE DELETE ON tasks
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
CREATE TRIGGER IF NOT EXISTS grocery_no_delete BEFORE DELETE ON grocery_items
BEGIN SELECT RAISE(ABORT, 'deleting rows is not allowed; set archived_at'); END;
"""

_TASK_COLUMNS = (
    "id, title, notes, assignee, due_date, recurrence, status, "
    "created_by, created_at, completed_at"
)
_GROCERY_COLUMNS = "id, name, quantity, checked, added_by, created_at"


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
    )


def _row_to_grocery(row: sqlite3.Row) -> GroceryItem:
    return GroceryItem(
        id=row["id"],
        name=row["name"],
        quantity=row["quantity"],
        checked=bool(row["checked"]),
        added_by=row["added_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteRepository:
    def __init__(self, path: str | Path = ":memory:", user_id: str = "local") -> None:
        self._user_id = user_id
        target = path if str(path) == ":memory:" else str(Path(path))
        try:
            # Streamlit runs scripts on worker threads, so allow cross-thread use.
            self._conn = sqlite3.connect(target, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            logger.exception("could not open sqlite database")
            raise BackendError("could not open database") from exc

    # ---- tasks -------------------------------------------------------
    def list_tasks(self, include_done: bool = False) -> list[Task]:
        sql = f"SELECT {_TASK_COLUMNS} FROM tasks WHERE archived_at IS NULL"
        if not include_done:
            sql += " AND status = 'open'"
        # NULL due dates sort last so dated chores surface first.
        sql += " ORDER BY due_date IS NULL, due_date, created_at"
        return [_row_to_task(r) for r in self._conn.execute(sql).fetchall()]

    def add_task(
        self,
        title: str,
        assignee: Assignee = "either",
        due_date: date | None = None,
        recurrence: Recurrence = "none",
        notes: str = "",
    ) -> Task:
        cleaned = rules.validate_task_fields(
            {
                "title": title,
                "assignee": assignee,
                "due_date": due_date,
                "recurrence": recurrence,
                "notes": notes,
            }
        )
        with self._conn:  # one transaction; _insert_task must not commit itself
            return self._insert_task(cleaned)

    def update_task(self, task_id: str, **fields: object) -> Task:
        cleaned = rules.validate_task_fields(fields)
        self._require_task(task_id)
        if cleaned:
            # Column names come from the validated allow-list, never from input.
            assignments = ", ".join(f"{col} = ?" for col in cleaned)
            values = [
                v.isoformat() if isinstance(v, date) else v for v in cleaned.values()
            ]
            with self._conn:
                self._conn.execute(
                    f"UPDATE tasks SET {assignments} WHERE id = ?", (*values, task_id)
                )
        return self._require_task(task_id)

    def complete_task(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.status == "done":
            return task  # idempotent: a double click must not spawn two occurrences
        now = rules.utc_now().isoformat()
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
                (now, task_id),
            )
            if task.recurrence != "none":
                self._insert_task(
                    {
                        "title": task.title,
                        "notes": task.notes,
                        "assignee": task.assignee,
                        "due_date": rules.next_due_date(task.due_date, task.recurrence),
                        "recurrence": task.recurrence,
                    }
                )
        return self._require_task(task_id)

    def reopen_task(self, task_id: str) -> Task:
        self._require_task(task_id)
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET status = 'open', completed_at = NULL WHERE id = ?",
                (task_id,),
            )
        return self._require_task(task_id)

    def archive_task(self, task_id: str) -> None:
        self._require_task(task_id)
        with self._conn:
            self._conn.execute(
                "UPDATE tasks SET archived_at = ? WHERE id = ?",
                (rules.utc_now().isoformat(), task_id),
            )

    # ---- grocery -----------------------------------------------------
    def list_grocery(self) -> list[GroceryItem]:
        rows = self._conn.execute(
            f"SELECT {_GROCERY_COLUMNS} FROM grocery_items "
            "WHERE archived_at IS NULL ORDER BY checked, created_at"
        ).fetchall()
        return [_row_to_grocery(r) for r in rows]

    def add_grocery(self, name: str, quantity: str = "") -> GroceryItem:
        clean_name = rules.clean_text(name, "name", rules.MAX_GROCERY_NAME, required=True)
        clean_qty = rules.clean_text(quantity, "quantity", rules.MAX_QUANTITY, required=False)
        item_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                "INSERT INTO grocery_items (id, name, quantity, checked, added_by, created_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (item_id, clean_name, clean_qty, self._user_id, rules.utc_now().isoformat()),
            )
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

    # ---- helpers -----------------------------------------------------
    def _insert_task(self, values: dict[str, object]) -> Task:
        task_id = str(uuid.uuid4())
        due = values.get("due_date")
        self._conn.execute(
            "INSERT INTO tasks (id, title, notes, assignee, due_date, recurrence, "
            "status, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (
                task_id,
                values["title"],
                values.get("notes", ""),
                values.get("assignee", "either"),
                due.isoformat() if isinstance(due, date) else None,
                values.get("recurrence", "none"),
                self._user_id,
                rules.utc_now().isoformat(),
            ),
        )
        return self._require_task(task_id)

    def _require_task(self, task_id: str) -> Task:
        row = self._conn.execute(
            f"SELECT {_TASK_COLUMNS} FROM tasks WHERE id = ? AND archived_at IS NULL",
            (task_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return _row_to_task(row)

    def _require_grocery(self, item_id: str) -> GroceryItem:
        row = self._conn.execute(
            f"SELECT {_GROCERY_COLUMNS} FROM grocery_items "
            "WHERE id = ? AND archived_at IS NULL",
            (item_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"grocery item {item_id} not found")
        return _row_to_grocery(row)
