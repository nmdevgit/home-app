"""Supabase (PostgREST) implementation of the Repository protocol.

`client` must already carry the user's JWT (see core.auth) so RLS applies.
No delete calls exist here by design; the DB would reject them anyway.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, TypeVar

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

_TASK_COLUMNS = (
    "id,title,notes,assignee,due_date,recurrence,status,created_by,created_at,completed_at,"
    "priority,rotate,completed_by"
)
_GROCERY_COLUMNS = "id,name,quantity,checked,added_by,created_at,category,price_cents"
_MEAL_COLUMNS = "id,day,slot,title,ingredients,created_by,created_at"
_BILL_COLUMNS = "id,name,amount_cents,due_date,recurrence,last_paid_on,created_by,created_at"
_NOTE_COLUMNS = "id,title,body,pinned,created_by,created_at,updated_at"
_SUBTASK_COLUMNS = "id,task_id,title,done,created_at"
_EXPENSE_COLUMNS = "id,day,description,amount_cents,paid_by,split,kind,created_by,created_at"
_TEMPLATE_COLUMNS = "id,kind,name,items,created_by,created_at"
_EVENT_COLUMNS = (
    "id,title,day,start_time,who,notes,recurrence,remind_days,created_by,created_at"
)
_GOAL_COLUMNS = "id,name,target_cents,due_date,icon,created_by,created_at"
_MOVE_COLUMNS = "id,goal_id,amount_cents,person,day,note,created_at"
_SPAWN_SLACK = timedelta(seconds=60)
_PURGE_CHUNK = 100  # ids per IN() filter, keeps the URL short
_EXPORT_PAGE = 1000  # PostgREST's default max rows per response
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
        completed_by=str(row["completed_by"]) if row.get("completed_by") else None,
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
        price_cents=row.get("price_cents"),
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


def _row_to_subtask(row: dict[str, Any]) -> Subtask:
    return Subtask(
        id=str(row["id"]),
        task_id=str(row["task_id"]),
        title=row["title"],
        done=bool(row["done"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_expense(row: dict[str, Any]) -> Expense:
    return Expense(
        id=str(row["id"]),
        day=date.fromisoformat(row["day"]),
        description=row["description"],
        amount_cents=int(row["amount_cents"]),
        paid_by=row["paid_by"],
        split=row["split"],
        kind=row["kind"],
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_template(row: dict[str, Any]) -> Template:
    return Template(
        id=str(row["id"]),
        kind=row["kind"],
        name=row["name"],
        items=row.get("items") or "",
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_event(row: dict[str, Any]) -> EventItem:
    return EventItem(
        id=str(row["id"]),
        title=row["title"],
        day=date.fromisoformat(row["day"]),
        start_time=time.fromisoformat(row["start_time"]) if row.get("start_time") else None,
        who=row["who"],
        notes=row.get("notes") or "",
        recurrence=row["recurrence"],
        remind_days=int(row["remind_days"]),
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_goal(row: dict[str, Any], saved: int) -> Goal:
    return Goal(
        id=str(row["id"]),
        name=row["name"],
        target_cents=int(row["target_cents"]),
        due_date=date.fromisoformat(row["due_date"]) if row.get("due_date") else None,
        icon=row["icon"],
        saved_cents=saved,
        created_by=str(row["created_by"]),
        created_at=_required_ts(row, "created_at"),
    )


def _row_to_move(row: dict[str, Any]) -> GoalMove:
    return GoalMove(
        id=str(row["id"]),
        goal_id=str(row["goal_id"]),
        amount_cents=int(row["amount_cents"]),
        person=row["person"],
        day=date.fromisoformat(row["day"]),
        note=row.get("note") or "",
        created_at=_required_ts(row, "created_at"),
    )


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("since must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _jsonable(fields: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in fields.items():
        if isinstance(value, time):
            out[key] = value.strftime("%H:%M")
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


class SupabaseRepository:
    def __init__(self, client: Any, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    # ---- permanent delete (needs migration 0005) ---------------------
    def delete_task(self, task_id: str) -> None:
        # Subtasks first: the FK may not cascade on databases without 0005.
        self._run(self._client.table("subtasks").delete().eq("task_id", task_id))
        self._delete_one("tasks", task_id, "task")

    def delete_subtask(self, subtask_id: str) -> None:
        self._delete_one("subtasks", subtask_id, "subtask")

    def delete_grocery(self, item_id: str) -> None:
        self._delete_one("grocery_items", item_id, "grocery item")

    def delete_checked_grocery(self) -> int:
        query = (
            self._client.table("grocery_items")
            .delete()
            .eq("checked", True)
            .is_("archived_at", "null")
        )
        return len(self._run(query))

    def delete_meal(self, meal_id: str) -> None:
        self._delete_one("meals", meal_id, "meal")

    def delete_bill(self, bill_id: str) -> None:
        self._delete_one("bills", bill_id, "bill")

    def delete_note(self, note_id: str) -> None:
        self._delete_one("notes", note_id, "note")

    def delete_expense(self, expense_id: str) -> None:
        self._delete_one("expenses", expense_id, "expense")

    def delete_template(self, template_id: str) -> None:
        self._delete_one("templates", template_id, "template")

    def purge_archived(self) -> int:
        total = 0
        # Subtasks of archived tasks go first (FK), then archived subtasks.
        archived = self._run(
            self._client.table("tasks")
            .select("id")
            .not_.is_("archived_at", "null")
            .limit(rules.MAX_EXPORT_LIMIT)
        )
        ids = [str(r["id"]) for r in archived]
        for start in range(0, len(ids), _PURGE_CHUNK):
            chunk = ids[start : start + _PURGE_CHUNK]
            total += len(
                self._run(self._client.table("subtasks").delete().in_("task_id", chunk))
            )
        archived_goals = self._run(
            self._client.table("goals")
            .select("id")
            .not_.is_("archived_at", "null")
            .limit(rules.MAX_EXPORT_LIMIT)
        )
        goal_ids = [str(r["id"]) for r in archived_goals]
        for start in range(0, len(goal_ids), _PURGE_CHUNK):
            chunk = goal_ids[start : start + _PURGE_CHUNK]
            total += len(
                self._run(self._client.table("goal_moves").delete().in_("goal_id", chunk))
            )
        for table in (
            "subtasks", "tasks", "grocery_items", "meals", "bills", "notes", "expenses",
            "templates", "events", "goals",
        ):
            query = self._client.table(table).delete().not_.is_("archived_at", "null")
            total += len(self._run(query))
        return total

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
            {
                "status": "done",
                "completed_at": rules.utc_now().isoformat(),
                "completed_by": self._user_id,
            },
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
            "tasks", task_id, {"status": "open", "completed_at": None, "completed_by": None}
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

    def set_grocery_price(self, item_id: str, price_cents: int | None) -> GroceryItem:
        cleaned = rules.clean_price_cents(price_cents)
        row = self._update_one("grocery_items", item_id, {"price_cents": cleaned})
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
        return self._lines_to_grocery(meal.ingredients)

    def _lines_to_grocery(self, text: str) -> int:
        query = (
            self._client.table("grocery_items")
            .select("name")
            .is_("archived_at", "null")
            .limit(rules.MAX_LIMIT)
        )
        seen = {r["name"].casefold() for r in self._run(query)}
        payloads: list[dict[str, object]] = []
        for line in text.splitlines():
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

    # ---- subtasks ----------------------------------------------------
    def list_subtasks(self, task_ids: list[str]) -> list[Subtask]:
        ids = rules.clean_task_ids(task_ids)
        if not ids:
            return []
        query = (
            self._client.table("subtasks")
            .select(_SUBTASK_COLUMNS)
            .in_("task_id", ids)
            .is_("archived_at", "null")
            .order("created_at")
            .limit(rules.MAX_SUBTASKS)
        )
        return [_row_to_subtask(r) for r in self._run(query)]

    def add_subtask(self, task_id: str, title: str) -> Subtask:
        clean = rules.clean_subtask_title(title)
        self._get_task(task_id)  # NotFoundError for a missing/archived task
        row = self._insert(
            "subtasks", {"task_id": task_id, "title": clean, "created_by": self._user_id}
        )
        return _row_to_subtask(row)

    def set_subtask_done(self, subtask_id: str, done: bool) -> Subtask:
        row = self._update_one("subtasks", subtask_id, {"done": rules.clean_bool(done, "done")})
        if row is None:
            raise NotFoundError(f"subtask {subtask_id} not found")
        return _row_to_subtask(row)

    def archive_subtask(self, subtask_id: str) -> None:
        self._archive("subtasks", subtask_id, "subtask")

    # ---- expenses ----------------------------------------------------
    def list_expenses(self, since: date | None = None, limit: int = DEFAULT_LIMIT) -> list[Expense]:
        query = self._client.table("expenses").select(_EXPENSE_COLUMNS).is_("archived_at", "null")
        if since is not None:
            query = query.gte("day", rules.clean_required_date(since, "since").isoformat())
        query = (
            query.order("day", desc=True)
            .order("created_at", desc=True)
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_expense(r) for r in self._run(query)]

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
        return _row_to_expense(self._insert("expenses", {**c, "created_by": self._user_id}))

    def archive_expense(self, expense_id: str) -> None:
        self._archive("expenses", expense_id, "expense")

    # ---- templates ---------------------------------------------------
    def list_templates(
        self, kind: TemplateKind | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Template]:
        query = self._client.table("templates").select(_TEMPLATE_COLUMNS).is_("archived_at", "null")
        if kind is not None:
            query = query.eq("kind", rules.clean_choice(kind, "kind", rules.TEMPLATE_KINDS))
        query = query.order("name").order("created_at").limit(rules.clamp_limit(limit))
        return [_row_to_template(r) for r in self._run(query)]

    def add_template(self, kind: TemplateKind, name: str, items: str) -> Template:
        clean_kind = rules.clean_choice(kind, "kind", rules.TEMPLATE_KINDS)
        cleaned = rules.validate_template_fields({"name": name, "items": items})
        row = self._insert(
            "templates", {**cleaned, "kind": clean_kind, "created_by": self._user_id}
        )
        return _row_to_template(row)

    def update_template(self, template_id: str, **fields: object) -> Template:
        cleaned = rules.validate_template_fields(fields)
        if not cleaned:
            return self._get_one("templates", _TEMPLATE_COLUMNS, template_id, _row_to_template)
        row = self._update_one("templates", template_id, cleaned)
        if row is None:
            raise NotFoundError(f"template {template_id} not found")
        return _row_to_template(row)

    def archive_template(self, template_id: str) -> None:
        self._archive("templates", template_id, "template")

    def template_to_grocery(self, template_id: str) -> int:
        tpl = self._get_one("templates", _TEMPLATE_COLUMNS, template_id, _row_to_template)
        return self._lines_to_grocery(tpl.items)

    # ---- people & export ---------------------------------------------
    def list_members(self) -> dict[str, Person]:
        rows = self._run(
            self._client.table("household_members").select("user_id,name").limit(rules.MAX_LIMIT)
        )
        return {str(r["user_id"]): r["name"] for r in rows if r.get("name") in rules.PEOPLE}

    def export_rows(self, table: str, limit: int = 5000) -> list[dict[str, object]]:
        name = rules.clean_export_table(table)
        wanted = rules.clamp_export_limit(limit)
        out: list[dict[str, object]] = []
        while len(out) < wanted:  # page it: PostgREST caps each response (default 1000)
            start = len(out)
            end = min(start + _EXPORT_PAGE, wanted) - 1
            query = (
                self._client.table(name)
                .select("*")
                .order("created_at")
                .order("id")
                .range(start, end)
            )
            page = self._run(query)
            out.extend({k: rules.export_value(v) for k, v in row.items()} for row in page)
            if len(page) < end - start + 1:
                break  # short page: no more rows
        return out[:wanted]

    # ---- round 4: activity, search ---------------------------------------
    def list_activity(self, since: datetime, limit: int = 50) -> list[Activity]:
        cut = _utc_iso(since)
        n = rules.clamp_limit(limit)
        members = self.list_members()
        out: list[Activity] = []

        def person(user_id: object) -> Person | None:
            return members.get(str(user_id)) if user_id else None

        def feed(table: str, columns: str, time_col: str, live_only: bool = True) -> Any:
            query = self._client.table(table).select(columns)
            if live_only:
                query = query.is_("archived_at", "null")
            return query, time_col

        def run(query_time: Any) -> list[dict[str, Any]]:
            query, time_col = query_time
            query = query.gte(time_col, cut).order(time_col, desc=True).limit(n)
            return self._run(query)

        done_q, done_col = feed("tasks", "id,title,completed_at,completed_by", "completed_at")
        for r in run((done_q.eq("status", "done"), done_col)):
            out.append(Activity(
                _required_ts(r, "completed_at"), person(r.get("completed_by")), "finished",
                "task", r["title"], str(r["id"]),
            ))
        for r in run(feed("tasks", "id,title,created_at,created_by", "created_at")):
            out.append(Activity(
                _required_ts(r, "created_at"), person(r.get("created_by")), "added", "task",
                r["title"], str(r["id"]),
            ))
        for r in run(feed("grocery_items", "id,name,created_at,added_by", "created_at")):
            out.append(Activity(
                _required_ts(r, "created_at"), person(r.get("added_by")), "added", "grocery",
                r["name"], str(r["id"]),
            ))
        for r in run(feed("expenses", "id,description,kind,created_at,created_by", "created_at")):
            out.append(Activity(
                _required_ts(r, "created_at"), person(r.get("created_by")),
                "settled" if r.get("kind") == "settlement" else "paid", "expense",
                r["description"], str(r["id"]),
            ))
        for r in run(feed("notes", "id,title,updated_at,created_by", "updated_at")):
            out.append(Activity(
                _required_ts(r, "updated_at"), person(r.get("created_by")), "updated", "note",
                r["title"], str(r["id"]),
            ))
        for r in run(feed("events", "id,title,created_at,created_by", "created_at")):
            out.append(Activity(
                _required_ts(r, "created_at"), person(r.get("created_by")), "added", "event",
                r["title"], str(r["id"]),
            ))
        moves = run(feed("goal_moves", "id,goal_id,amount_cents,person,created_at", "created_at",
                         live_only=False))
        names = self._goal_names({str(m["goal_id"]) for m in moves})
        for m in moves:
            if str(m["goal_id"]) not in names:
                continue
            out.append(Activity(
                _required_ts(m, "created_at"), m.get("person"),
                "saved to" if int(m["amount_cents"]) > 0 else "withdrew from", "goal",
                names[str(m["goal_id"])], str(m["id"]),
            ))
        out.sort(key=lambda a: a.at, reverse=True)
        return out[:n]

    def _goal_names(self, goal_ids: set[str]) -> dict[str, str]:
        if not goal_ids:
            return {}
        rows = self._run(
            self._client.table("goals").select("id,name").in_("id", sorted(goal_ids))
        )
        return {str(r["id"]): r["name"] for r in rows}

    def search(self, query: str, limit: int = 40) -> list[SearchHit]:
        text = rules.sanitize_search(query)  # filter-special characters are removed
        cap = rules.clamp_limit(limit)
        per = rules.SEARCH_PER_SOURCE
        # (kind, page, table, title column, snippet column or None, searched columns)
        sources: tuple[tuple[str, str, str, str, str | None, tuple[str, ...]], ...] = (
            ("task", "tasks", "tasks", "title", "notes", ("title", "notes")),
            ("grocery", "grocery", "grocery_items", "name", "quantity", ("name",)),
            ("note", "notes", "notes", "title", "body", ("title", "body")),
            ("meal", "meals", "meals", "title", "ingredients", ("title",)),
            ("template", "templates", "templates", "name", "items", ("name", "items")),
            ("bill", "bills", "bills", "name", "due_date", ("name",)),
            ("event", "calendar", "events", "title", "day", ("title",)),
            ("goal", "goals", "goals", "name", None, ("name",)),
        )
        hits: list[SearchHit] = []
        for kind, page, table, title_col, snip_col, cols in sources:
            select = f"id,{title_col}" + (f",{snip_col}" if snip_col else "")
            q = self._client.table(table).select(select).is_("archived_at", "null")
            if len(cols) == 1:
                q = q.ilike(cols[0], f"%{text}%")
            else:
                q = q.or_(",".join(f'{c}.ilike."*{text}*"' for c in cols))
            for r in self._run(q.limit(per)):
                raw = str(r.get(snip_col) or "") if snip_col else ""
                snip = f"due {raw}" if kind == "bill" else rules.snippet(raw)
                hits.append(SearchHit(kind, str(r["id"]), r[title_col], snip, page))
        return hits[:cap]

    # ---- round 4: bulk, undo, restores -------------------------------------
    def bulk_complete_tasks(self, task_ids: list[str]) -> int:
        count = 0
        for task_id in rules.clean_bulk_ids(task_ids):
            try:
                if self._get_task(task_id).status == "open":
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
        query = (
            self._client.table("tasks")
            .update(_jsonable(cleaned))
            .in_("id", ids)
            .is_("archived_at", "null")
        )
        return len(self._run(query))

    def bulk_archive_tasks(self, task_ids: list[str]) -> int:
        ids = rules.clean_bulk_ids(task_ids)
        if not ids:
            return 0
        query = (
            self._client.table("tasks")
            .update({"archived_at": rules.utc_now().isoformat()})
            .in_("id", ids)
            .is_("archived_at", "null")
        )
        return len(self._run(query))

    def bulk_delete_tasks(self, task_ids: list[str]) -> int:
        ids = rules.clean_bulk_ids(task_ids)
        if not ids:
            return 0
        self._run(self._client.table("subtasks").delete().in_("task_id", ids))
        return len(self._run(self._client.table("tasks").delete().in_("id", ids)))

    def undo_complete(self, task_id: str) -> Task:
        task = self._get_task(task_id)
        if task.status == "done" and task.recurrence != "none" and task.completed_at:
            expected = rules.swap_assignee(task.assignee) if task.rotate else task.assignee
            query = (
                self._client.table("tasks")
                .select("id")
                .is_("archived_at", "null")
                .eq("status", "open")
                .eq("title", task.title)
                .eq("notes", task.notes)
                .eq("recurrence", task.recurrence)
                .eq("priority", task.priority)
                .eq("rotate", task.rotate)
                .eq("assignee", expected)
                .gte("created_at", _utc_iso(task.completed_at - _SPAWN_SLACK))
                .order("created_at", desc=True)
                .limit(5)
            )
            for row in self._run(query):
                cid = str(row["id"])
                if cid == task_id:
                    continue
                kids = self._run(
                    self._client.table("subtasks").select("id").eq("task_id", cid).limit(1)
                )
                if not kids:  # untouched: no subtasks were added
                    self._run(self._client.table("tasks").delete().eq("id", cid))
                    break
        return self.reopen_task(task_id)

    def restore_meal(self, meal_id: str) -> Meal:
        return _row_to_meal(self._restore("meals", meal_id, "meal"))

    def restore_bill(self, bill_id: str) -> Bill:
        return _row_to_bill(self._restore("bills", bill_id, "bill"))

    def restore_note(self, note_id: str) -> Note:
        return _row_to_note(self._restore("notes", note_id, "note"))

    def restore_expense(self, expense_id: str) -> Expense:
        return _row_to_expense(self._restore("expenses", expense_id, "expense"))

    def restore_template(self, template_id: str) -> Template:
        return _row_to_template(self._restore("templates", template_id, "template"))

    def list_archived_items(self, limit: int = DEFAULT_LIMIT) -> list[ArchivedItem]:
        items: list[ArchivedItem] = []
        for kind, (table, columns) in rules.ARCHIVED_SOURCES.items():
            for row in self._list_archived(table, columns.replace(", ", ","), limit):
                title, detail = rules.archived_title_detail(kind, row)
                archived = _ts(row["archived_at"])
                if archived is None:
                    raise BackendError("archived row missing archived_at")
                items.append(ArchivedItem(kind, str(row["id"]), title, detail, archived))  # type: ignore[arg-type]
        items.sort(key=lambda i: i.archived_at, reverse=True)
        return items

    def restore_item(self, kind: ArchivedKind, item_id: str) -> None:
        rules.check_archived_kind(kind)
        table = rules.ARCHIVED_SOURCES[kind][0]
        if kind == "subtask":
            rows = self._run(
                self._client.table("subtasks")
                .select("task_id")
                .eq("id", item_id)
                .not_.is_("archived_at", "null")
            )
            if not rows:
                raise NotFoundError(f"archived subtask {item_id} not found")
            parent = self._run(
                self._client.table("tasks")
                .select("id")
                .eq("id", rows[0]["task_id"])
                .is_("archived_at", "null")
            )
            if not parent:
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
        query = (
            self._client.table("events")
            .select(_EVENT_COLUMNS)
            .is_("archived_at", "null")
            .lte("day", hi.isoformat())
            .or_(f"recurrence.neq.none,day.gte.{lo.isoformat()}")
            .order("day")
            .limit(rules.MAX_LIMIT)
        )
        found = [
            EventOccurrence(ev, d)
            for ev in (_row_to_event(r) for r in self._run(query))
            for d in rules.event_occurrences(ev, lo, hi)
        ]
        found.sort(key=lambda o: (o.on, o.event.start_time or time.min, o.event.title))
        return found[: rules.clamp_limit(limit)]

    def upcoming_events(
        self, today: date, days: int = 60, limit: int = 10
    ) -> list[EventOccurrence]:
        first = rules.clean_required_date(today, "today")
        span = rules.clean_int_range(days, "days", 1, 366)
        return self.list_events(first, first + timedelta(days=span), limit)

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
        return _row_to_event(self._insert("events", {**c, "created_by": self._user_id}))

    def update_event(self, event_id: str, **fields: object) -> EventItem:
        cleaned = rules.validate_event_fields(fields)
        if not cleaned:
            return self._get_one("events", _EVENT_COLUMNS, event_id, _row_to_event)
        row = self._update_one("events", event_id, cleaned)
        if row is None:
            raise NotFoundError(f"event {event_id} not found")
        return _row_to_event(row)

    def archive_event(self, event_id: str) -> None:
        self._archive("events", event_id, "event")

    def restore_event(self, event_id: str) -> EventItem:
        return _row_to_event(self._restore("events", event_id, "event"))

    def delete_event(self, event_id: str) -> None:
        self._delete_one("events", event_id, "event")

    # ---- goals -------------------------------------------------------------------
    def list_goals(self, limit: int = 50) -> list[Goal]:
        query = (
            self._client.table("goals")
            .select(_GOAL_COLUMNS)
            .is_("archived_at", "null")
            .order("created_at")
            .limit(rules.clamp_limit(limit))
        )
        rows = self._run(query)
        saved = self._saved_by_goal([str(r["id"]) for r in rows])
        return [_row_to_goal(r, saved.get(str(r["id"]), 0)) for r in rows]

    def _saved_by_goal(self, goal_ids: list[str]) -> dict[str, int]:
        """Sum of moves per goal: one paged query (PostgREST caps a response at 1000)."""
        totals: dict[str, int] = {}
        if not goal_ids:
            return totals
        for start in range(0, rules.MAX_GOAL_MOVES_SUM, _EXPORT_PAGE):
            query = (
                self._client.table("goal_moves")
                .select("goal_id,amount_cents")
                .in_("goal_id", goal_ids)
                .order("created_at")
                .order("id")
                .range(start, start + _EXPORT_PAGE - 1)
            )
            page = self._run(query)
            for r in page:
                gid = str(r["goal_id"])
                totals[gid] = totals.get(gid, 0) + int(r["amount_cents"])
            if len(page) < _EXPORT_PAGE:
                break
        return totals

    def _get_goal(self, goal_id: str) -> Goal:
        row = self._get_one("goals", _GOAL_COLUMNS, goal_id, dict)
        return _row_to_goal(row, self._saved_by_goal([goal_id]).get(goal_id, 0))

    def add_goal(
        self, name: str, target_cents: int, due_date: date | None = None, icon: str = "savings"
    ) -> Goal:
        c = rules.validate_goal_fields(
            {"name": name, "target_cents": target_cents, "due_date": due_date, "icon": icon}
        )
        return _row_to_goal(self._insert("goals", {**c, "created_by": self._user_id}), 0)

    def update_goal(self, goal_id: str, **fields: object) -> Goal:
        cleaned = rules.validate_goal_fields(fields)
        if cleaned:
            if self._update_one("goals", goal_id, cleaned) is None:
                raise NotFoundError(f"goal {goal_id} not found")
        return self._get_goal(goal_id)

    def archive_goal(self, goal_id: str) -> None:
        self._archive("goals", goal_id, "goal")

    def delete_goal(self, goal_id: str) -> None:
        # Moves first: the FK cascades after 0006, but this works without it too.
        self._run(self._client.table("goal_moves").delete().eq("goal_id", goal_id))
        self._delete_one("goals", goal_id, "goal")

    def add_goal_move(
        self, goal_id: str, amount_cents: int, person: Person, note: str = ""
    ) -> GoalMove:
        c = rules.validate_goal_move(amount_cents, person, note)
        self._get_one("goals", "id", goal_id, dict)  # NotFoundError if missing/archived
        row = self._insert(
            "goal_moves",
            {**c, "goal_id": goal_id, "day": clock.today(), "created_by": self._user_id},
        )
        return _row_to_move(row)

    def list_goal_moves(self, goal_id: str, limit: int = 50) -> list[GoalMove]:
        query = (
            self._client.table("goal_moves")
            .select(_MOVE_COLUMNS)
            .eq("goal_id", goal_id)
            .order("created_at", desc=True)
            .limit(rules.clamp_limit(limit))
        )
        return [_row_to_move(r) for r in self._run(query)]

    def delete_goal_move(self, move_id: str) -> None:
        self._delete_one("goal_moves", move_id, "goal move")

    # ---- prefs ---------------------------------------------------------------------
    def get_prefs(self) -> Prefs:
        rows = self._run(
            self._client.table("user_prefs")
            .select("accent,pinned,start_page,compact")
            .eq("user_id", self._user_id)
            .limit(1)
        )
        if not rows:
            return Prefs()
        r = rows[0]
        return Prefs(
            accent=r.get("accent") or "teal",
            pinned=rules.parse_pinned(r.get("pinned")),
            start_page=r.get("start_page") or "today",
            compact=bool(r.get("compact")),
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
        values: dict[str, object] = {
            **merged,
            "pinned": ",".join(merged["pinned"]),  # type: ignore[arg-type]
        }
        # update-then-insert (not upsert): ON CONFLICT would need UPDATE on user_id too.
        rows = self._run(
            self._client.table("user_prefs").update(values).eq("user_id", self._user_id)
        )
        if not rows:
            self._run(
                self._client.table("user_prefs").insert({**values, "user_id": self._user_id})
            )
        return self.get_prefs()

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

    def _delete_one(self, table: str, row_id: str, label: str) -> None:
        """Permanently deletes one row (active or archived); NotFoundError if absent."""
        rows = self._run(self._client.table(table).delete().eq("id", row_id))
        if not rows:
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
