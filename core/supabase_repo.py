"""Supabase (PostgREST) implementation of the Repository protocol.

`client` must already carry the user's JWT (see core.auth) so RLS applies.
No delete calls exist here by design; the DB would reject them anyway.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from core import clock, rules
from core.errors import BackendError, NotFoundError, ValidationError
from core.repo import (
    DEFAULT_LIMIT,
    Assignee,
    Bill,
    BillRecurrence,
    GroceryCategory,
    GroceryItem,
    Meal,
    MealSlot,
    Note,
    Priority,
    Recurrence,
    StorageUsage,
    Task,
)

logger = logging.getLogger(__name__)

_TASK_COLUMNS = (
    "id,title,notes,assignee,due_date,recurrence,status,created_by,created_at,completed_at,"
    "priority,rotate"
)
_GROCERY_COLUMNS = "id,name,quantity,checked,added_by,created_at,category"
_MEAL_COLUMNS = "id,day,slot,title,ingredients,created_by,created_at"
_BILL_COLUMNS = "id,name,amount_cents,due_date,recurrence,last_paid_on,created_by,created_at"
_NOTE_COLUMNS = "id,title,body,pinned,created_by,created_at,updated_at"
STORAGE_LIMIT_BYTES = 500 * 1024 * 1024
_T = TypeVar("_T")


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
        priority=row.get("priority") or "normal",
        rotate=bool(row.get("rotate")),
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
        category=row.get("category") or "other",
    )


def _required_ts(row: dict[str, Any], key: str) -> datetime:
    value = _ts(row.get(key))
    if value is None:
        raise BackendError(f"row missing {key}")
    return value


def _row_to_meal(row: dict[str, Any]) -> Meal:
    return Meal(
        id=str(row["id"]),
        day=date.fromisoformat(row["day"]),
        slot=row["slot"],
        title=row["title"],
        ingredients=row.get("ingredients") or "",
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_bill(row: dict[str, Any]) -> Bill:
    return Bill(
        id=str(row["id"]),
        name=row["name"],
        amount_cents=int(row["amount_cents"]),
        due_date=date.fromisoformat(row["due_date"]),
        recurrence=row["recurrence"],
        last_paid_on=date.fromisoformat(row["last_paid_on"]) if row.get("last_paid_on") else None,
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_note(row: dict[str, Any]) -> Note:
    return Note(
        id=str(row["id"]),
        title=row["title"],
        body=row.get("body") or "",
        pinned=bool(row["pinned"]),
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
        updated_at=_required_ts(row, "updated_at"),
    )


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("since must be timezone-aware")
    return value.astimezone(UTC).isoformat()


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
    def list_tasks(
        self, include_done: bool = False, limit: int = DEFAULT_LIMIT
    ) -> list[Task]:
        query = self._client.table("tasks").select(_TASK_COLUMNS).is_("archived_at", "null")
        if not include_done:
            query = query.eq("status", "open")
        # nullsfirst=False keeps undated tasks at the end.
        query = (
            query.order("due_date", desc=False, nullsfirst=False)
            .order("created_at")
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_task(r) for r in self._run(query)]

    def list_done_tasks(self, since: datetime, limit: int = DEFAULT_LIMIT) -> list[Task]:
        query = (
            self._client.table("tasks")
            .select(_TASK_COLUMNS)
            .is_("archived_at", "null")
            .eq("status", "done")
            .gte("completed_at", _utc_iso(since))
            .order("completed_at", desc=True)
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_task(r) for r in self._run(query)]

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
                    "assignee": (
                        rules.swap_assignee(task.assignee) if task.rotate else task.assignee
                    ),
                    "due_date": rules.next_due_date(task.due_date, task.recurrence),
                    "recurrence": task.recurrence,
                    "priority": task.priority,
                    "rotate": task.rotate,
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
        self._archive("tasks", task_id, "task")

    def list_archived_tasks(self, limit: int = DEFAULT_LIMIT) -> list[Task]:
        return [_row_to_task(r) for r in self._list_archived("tasks", _TASK_COLUMNS, limit)]

    def restore_task(self, task_id: str) -> Task:
        return _row_to_task(self._restore("tasks", task_id, "task"))

    # ---- grocery -----------------------------------------------------
    def list_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]:
        query = (
            self._client.table("grocery_items")
            .select(_GROCERY_COLUMNS)
            .is_("archived_at", "null")
            .order("checked")
            .order("created_at")
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_grocery(r) for r in self._run(query)]

    def add_grocery(
        self, name: str, quantity: str = "", category: GroceryCategory = "other"
    ) -> GroceryItem:
        cleaned = rules.validate_grocery_fields(
            {"name": name, "quantity": quantity, "category": category}
        )
        return self._insert_grocery(cleaned)

    def update_grocery(self, item_id: str, **fields: object) -> GroceryItem:
        cleaned = rules.validate_grocery_fields(fields)
        if not cleaned:
            return self._get_one("grocery_items", _GROCERY_COLUMNS, item_id, _row_to_grocery)
        row = self._update_one("grocery_items", item_id, cleaned)
        if row is None:
            raise NotFoundError(f"grocery item {item_id} not found")
        return _row_to_grocery(row)

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

    def list_archived_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]:
        rows = self._list_archived("grocery_items", _GROCERY_COLUMNS, limit)
        return [_row_to_grocery(r) for r in rows]

    def restore_grocery(self, item_id: str) -> GroceryItem:
        return _row_to_grocery(self._restore("grocery_items", item_id, "grocery item"))

    def frequent_grocery(self, limit: int = 12) -> list[tuple[str, GroceryCategory]]:
        query = (
            self._client.table("grocery_items")
            .select("name,category")
            .order("created_at", desc=True)
            .limit(500)
        )  # includes archived rows on purpose
        rows = [(r["name"], r.get("category") or "other") for r in self._run(query)]
        return rules.frequent_names(rows, limit)  # type: ignore[return-value]

    # ---- meals -------------------------------------------------------
    def list_meals(self, start: date, end: date, limit: int = DEFAULT_LIMIT) -> list[Meal]:
        query = (
            self._client.table("meals")
            .select(_MEAL_COLUMNS)
            .is_("archived_at", "null")
            .gte("day", rules.clean_required_date(start, "start").isoformat())
            .lte("day", rules.clean_required_date(end, "end").isoformat())
            .order("day")
            .order("created_at")
            .limit(rules.clamp_limit(limit))
        )
        meals = [_row_to_meal(r) for r in self._run(query)]
        return sorted(meals, key=lambda m: (m.day, rules.SLOT_ORDER[m.slot]))

    def add_meal(
        self, day: date, title: str, ingredients: str = "", slot: MealSlot = "dinner"
    ) -> Meal:
        cleaned = rules.validate_meal_fields(
            {"day": day, "title": title, "ingredients": ingredients, "slot": slot}
        )
        row = self._insert("meals", {**cleaned, "created_by": self._user_id})
        return _row_to_meal(row)

    def update_meal(self, meal_id: str, **fields: object) -> Meal:
        cleaned = rules.validate_meal_fields(fields)
        if not cleaned:
            return self._get_one("meals", _MEAL_COLUMNS, meal_id, _row_to_meal)
        row = self._update_one("meals", meal_id, cleaned)
        if row is None:
            raise NotFoundError(f"meal {meal_id} not found")
        return _row_to_meal(row)

    def archive_meal(self, meal_id: str) -> None:
        self._archive("meals", meal_id, "meal")

    def meal_to_grocery(self, meal_id: str) -> int:
        meal = self._get_one("meals", _MEAL_COLUMNS, meal_id, _row_to_meal)
        query = (
            self._client.table("grocery_items")
            .select("name")
            .is_("archived_at", "null")
            .limit(rules.MAX_LIMIT)
        )
        seen = {r["name"].casefold() for r in self._run(query)}
        payloads: list[dict[str, object]] = []
        for line in meal.ingredients.splitlines():
            name = line.strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            payloads.append(
                {"name": name, "quantity": "", "category": "other", "added_by": self._user_id}
            )
        if payloads:  # one request, so a failure adds nothing
            self._run(self._client.table("grocery_items").insert(payloads))
        return len(payloads)

    # ---- bills -------------------------------------------------------
    def list_bills(self, limit: int = DEFAULT_LIMIT) -> list[Bill]:
        query = (
            self._client.table("bills")
            .select(_BILL_COLUMNS)
            .is_("archived_at", "null")
            .order("due_date")
            .order("name")
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_bill(r) for r in self._run(query)]

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
        return _row_to_bill(self._insert("bills", {**cleaned, "created_by": self._user_id}))

    def update_bill(self, bill_id: str, **fields: object) -> Bill:
        cleaned = rules.validate_bill_fields(fields)
        if not cleaned:
            return self._get_one("bills", _BILL_COLUMNS, bill_id, _row_to_bill)
        row = self._update_one("bills", bill_id, cleaned)
        if row is None:
            raise NotFoundError(f"bill {bill_id} not found")
        return _row_to_bill(row)

    def mark_bill_paid(self, bill_id: str) -> Bill:
        bill = self._get_one("bills", _BILL_COLUMNS, bill_id, _row_to_bill)
        today = clock.today()
        new_due = rules.next_bill_due(bill.due_date, bill.recurrence, today)
        row = self._update_one("bills", bill_id, {"last_paid_on": today, "due_date": new_due})
        if row is None:
            raise NotFoundError(f"bill {bill_id} not found")
        return _row_to_bill(row)

    def archive_bill(self, bill_id: str) -> None:
        self._archive("bills", bill_id, "bill")

    # ---- notes -------------------------------------------------------
    def list_notes(self, limit: int = DEFAULT_LIMIT) -> list[Note]:
        query = (
            self._client.table("notes")
            .select(_NOTE_COLUMNS)
            .is_("archived_at", "null")
            .order("pinned", desc=True)
            .order("updated_at", desc=True)
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_note(r) for r in self._run(query)]

    def add_note(self, title: str, body: str = "", pinned: bool = False) -> Note:
        cleaned = rules.validate_note_fields({"title": title, "body": body, "pinned": pinned})
        return _row_to_note(self._insert("notes", {**cleaned, "created_by": self._user_id}))

    def update_note(self, note_id: str, **fields: object) -> Note:
        cleaned = rules.validate_note_fields(fields)
        if not cleaned:
            return self._get_one("notes", _NOTE_COLUMNS, note_id, _row_to_note)
        row = self._update_one("notes", note_id, cleaned)  # updated_at set by DB trigger
        if row is None:
            raise NotFoundError(f"note {note_id} not found")
        return _row_to_note(row)

    def archive_note(self, note_id: str) -> None:
        self._archive("notes", note_id, "note")

    # ---- storage meter -----------------------------------------------
    def storage_usage(self) -> StorageUsage:
        try:
            data = self._client.rpc("db_size").execute().data
            if isinstance(data, list):
                data = data[0] if data else None
            if isinstance(data, dict):
                data = next(iter(data.values()), None)
            used = int(data)  # type: ignore[arg-type]
        except Exception as exc:
            logger.exception("supabase db_size failed")
            raise BackendError("could not read storage usage") from exc
        return StorageUsage(used_bytes=used, limit_bytes=STORAGE_LIMIT_BYTES)

    # ---- helpers -----------------------------------------------------
    def _insert(self, table: str, values: dict[str, object]) -> dict[str, Any]:
        rows = self._run(self._client.table(table).insert(_jsonable(values)))
        if not rows:
            raise BackendError("insert returned no row")
        return rows[0]

    def _insert_task(self, values: dict[str, object]) -> Task:
        return _row_to_task(self._insert("tasks", {**values, "created_by": self._user_id}))

    def _insert_grocery(self, values: dict[str, object]) -> GroceryItem:
        row = self._insert("grocery_items", {**values, "added_by": self._user_id})
        return _row_to_grocery(row)

    def _archive(self, table: str, row_id: str, label: str) -> None:
        row = self._update_one(table, row_id, {"archived_at": rules.utc_now().isoformat()})
        if row is None:
            raise NotFoundError(f"{label} {row_id} not found")

    def _list_archived(self, table: str, columns: str, limit: int) -> list[dict[str, Any]]:
        query = (
            self._client.table(table)
            .select(columns)
            .not_.is_("archived_at", "null")
            .order("archived_at", desc=True)
            .limit(rules.clamp_limit(limit))
        )
        return self._run(query)

    def _restore(self, table: str, row_id: str, label: str) -> dict[str, Any]:
        query = (
            self._client.table(table)
            .update({"archived_at": None})
            .eq("id", row_id)
            .not_.is_("archived_at", "null")
        )
        rows = self._run(query)
        if not rows:
            raise NotFoundError(f"archived {label} {row_id} not found")
        return rows[0]

    def _get_one(
        self, table: str, columns: str, row_id: str, convert: Callable[[dict[str, Any]], _T]
    ) -> _T:
        query = (
            self._client.table(table).select(columns).eq("id", row_id).is_("archived_at", "null")
        )
        rows = self._run(query)
        if not rows:
            raise NotFoundError(f"{table} row {row_id} not found")
        return convert(rows[0])

    def _get_task(self, task_id: str) -> Task:
        return self._get_one("tasks", _TASK_COLUMNS, task_id, _row_to_task)
