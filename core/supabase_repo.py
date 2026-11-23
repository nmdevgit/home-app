"""Supabase (PostgREST) implementation of the Repository protocol.

`client` must already carry the user's JWT (see core.auth) so RLS applies.
No delete calls exist here by design; the DB would reject them anyway.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from core import rules
from core.errors import BackendError, NotFoundError
from core.repo import Assignee, GroceryItem, Recurrence, Task

logger = logging.getLogger(__name__)

_TASK_COLUMNS = (
    "id,title,notes,assignee,due_date,recurrence,status,created_by,created_at,completed_at"
)
_GROCERY_COLUMNS = "id,name,quantity,checked,added_by,created_at"


def _ts(value: str | None) -> datetime | None:
    # Postgres may emit a trailing 'Z'; older fromisoformat() rejects it.
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _row_to_task(row: dict[str, Any]) -> Task:
    created = _ts(row["created_at"])
    if created is None:
        raise BackendError("task row missing created_at")
    return Task(
        id=str(row["id"]),
        title=row["title"],
        notes=row.get("notes") or "",
        assignee=row["assignee"],
        due_date=date.fromisoformat(row["due_date"]) if row.get("due_date") else None,
        recurrence=row["recurrence"],
        status=row["status"],
        created_by=str(row["created_by"]),
        created_at=created,
        completed_at=_ts(row.get("completed_at")),
    )


def _row_to_grocery(row: dict[str, Any]) -> GroceryItem:
    created = _ts(row["created_at"])
    if created is None:
        raise BackendError("grocery row missing created_at")
    return GroceryItem(
        id=str(row["id"]),
        name=row["name"],
        quantity=row.get("quantity") or "",
        checked=bool(row["checked"]),
        added_by=str(row["added_by"]),
        created_at=created,
    )


def _jsonable(fields: dict[str, object]) -> dict[str, object]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in fields.items()}


class SupabaseRepository:
    def __init__(self, client: Any, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    def _run(self, query: Any) -> list[dict[str, Any]]:
        """Execute a postgrest query, normalising failures to BackendError."""
        try:
            return list(query.execute().data or [])
        except Exception as exc:
            logger.exception("supabase request failed")
            raise BackendError("database request failed") from exc

    def _update_one(
        self,
        table: str,
        row_id: str,
        values: dict[str, object],
        extra_eq: dict[str, object] | None = None,
    ) -> dict[str, Any] | None:
        query = (
            self._client.table(table)
            .update(_jsonable(values))
            .eq("id", row_id)
            .is_("archived_at", "null")
        )
        for col, val in (extra_eq or {}).items():
            query = query.eq(col, val)
        rows = self._run(query)
        return rows[0] if rows else None

    # ---- tasks -------------------------------------------------------
    def list_tasks(self, include_done: bool = False) -> list[Task]:
        query = self._client.table("tasks").select(_TASK_COLUMNS).is_("archived_at", "null")
        if not include_done:
            query = query.eq("status", "open")
        # nullsfirst=False keeps undated tasks at the end.
        query = query.order("due_date", desc=False, nullsfirst=False).order("created_at")
        return [_row_to_task(r) for r in self._run(query)]

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
        return self._insert_task(cleaned)

    def update_task(self, task_id: str, **fields: object) -> Task:
        cleaned = rules.validate_task_fields(fields)
        if not cleaned:
            return self._get_task(task_id)
        row = self._update_one("tasks", task_id, cleaned)
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return _row_to_task(row)

    def complete_task(self, task_id: str) -> Task:
        task = self._get_task(task_id)
        if task.status == "done":
            return task
        # Guard on status='open' so a concurrent double-complete (Nick and Natalie
        # tapping at once) cannot create two next occurrences. The two calls are
        # not one transaction: if the insert fails (network drop) after the update,
        # the task is done but its next occurrence is missing (never duplicated);
        # accepted for v1 - the user can re-add it. A Postgres function would fix it.
        row = self._update_one(
            "tasks",
            task_id,
            {"status": "done", "completed_at": rules.utc_now().isoformat()},
            extra_eq={"status": "open"},
        )
        if row is None:
            return self._get_task(task_id)
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
        return _row_to_task(row)

    def reopen_task(self, task_id: str) -> Task:
        row = self._update_one(
            "tasks", task_id, {"status": "open", "completed_at": None}
        )
        if row is None:
            raise NotFoundError(f"task {task_id} not found")
        return _row_to_task(row)

    def archive_task(self, task_id: str) -> None:
        row = self._update_one(
            "tasks", task_id, {"archived_at": rules.utc_now().isoformat()}
        )
        if row is None:
            raise NotFoundError(f"task {task_id} not found")

    # ---- grocery -----------------------------------------------------
    def list_grocery(self) -> list[GroceryItem]:
        query = (
            self._client.table("grocery_items")
            .select(_GROCERY_COLUMNS)
            .is_("archived_at", "null")
            .order("checked")
            .order("created_at")
        )
        return [_row_to_grocery(r) for r in self._run(query)]

    def add_grocery(self, name: str, quantity: str = "") -> GroceryItem:
        payload = {
            "name": rules.clean_text(name, "name", rules.MAX_GROCERY_NAME, required=True),
            "quantity": rules.clean_text(
                quantity, "quantity", rules.MAX_QUANTITY, required=False
            ),
            "added_by": self._user_id,
        }
        rows = self._run(self._client.table("grocery_items").insert(payload))
        if not rows:
            raise BackendError("insert returned no row")
        return _row_to_grocery(rows[0])

    def set_grocery_checked(self, item_id: str, checked: bool) -> GroceryItem:
        row = self._update_one(
            "grocery_items", item_id, {"checked": bool(checked)}
        )
        if row is None:
            raise NotFoundError(f"grocery item {item_id} not found")
        return _row_to_grocery(row)

    def archive_checked_grocery(self) -> int:
        query = (
            self._client.table("grocery_items")
            .update({"archived_at": rules.utc_now().isoformat()})
            .eq("checked", True)
            .is_("archived_at", "null")
        )
        return len(self._run(query))

    # ---- helpers -----------------------------------------------------
    def _insert_task(self, values: dict[str, object]) -> Task:
        payload = _jsonable({**values, "created_by": self._user_id})
        rows = self._run(self._client.table("tasks").insert(payload))
        if not rows:
            raise BackendError("insert returned no row")
        return _row_to_task(rows[0])

    def _get_task(self, task_id: str) -> Task:
        query = (
            self._client.table("tasks")
            .select(_TASK_COLUMNS)
            .eq("id", task_id)
            .is_("archived_at", "null")
        )
        rows = self._run(query)
        if not rows:
            raise NotFoundError(f"task {task_id} not found")
        return _row_to_task(rows[0])
