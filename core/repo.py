"""Shared contract between backend and frontend. PM-owned: change only via PM.

Rules: NO hard deletes anywhere ('archive_*' sets archived_at; archived rows are
hidden from list_* but kept; 'restore_*' clears archived_at). Every list_* takes a
`limit` so pages never load unbounded data (free-tier memory limits).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

Assignee = Literal["nick", "natalie", "either"]
Recurrence = Literal["none", "daily", "weekly", "monthly"]
TaskStatus = Literal["open", "done"]
Priority = Literal["high", "normal", "low"]
GroceryCategory = Literal[
    "produce", "dairy", "meat", "bakery", "pantry", "frozen", "drinks", "household", "other"
]
MealSlot = Literal["breakfast", "lunch", "dinner"]
BillRecurrence = Literal["none", "weekly", "fortnightly", "monthly", "yearly"]
Person = Literal["nick", "natalie"]
ExpenseSplit = Literal["equal", "payer_only", "other_only"]
ExpenseKind = Literal["expense", "settlement"]
TemplateKind = Literal["shopping", "recipe"]
EXPORT_TABLES = (
    "tasks", "subtasks", "grocery_items", "meals", "bills", "notes", "expenses", "templates",
)

DEFAULT_LIMIT = 300


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    notes: str
    assignee: Assignee
    due_date: date | None
    recurrence: Recurrence
    status: TaskStatus
    created_by: str  # user id
    created_at: datetime
    completed_at: datetime | None
    priority: Priority = "normal"
    # When a recurring task is completed, the next occurrence swaps nick<->natalie
    # ('either' stays 'either').
    rotate: bool = False
    completed_by: str | None = None  # user id of who ticked it done (set by complete_task)


@dataclass(frozen=True)
class Subtask:
    id: str
    task_id: str
    title: str
    done: bool
    created_at: datetime


@dataclass(frozen=True)
class Expense:
    """kind='expense': `paid_by` paid `amount_cents` for `description`, split per `split`
    (equal: half each; payer_only: only payer's cost, no debt; other_only: the other person
    owes the whole amount). kind='settlement': `paid_by` handed `amount_cents` to the other."""
    id: str
    day: date
    description: str
    amount_cents: int  # integer cents, 1..100_000_000
    paid_by: Person
    split: ExpenseSplit
    kind: ExpenseKind
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class Template:
    """Reusable list: a shopping template ('weekly shop') or a recipe."""
    id: str
    kind: TemplateKind
    name: str
    items: str  # one item/ingredient per line, max 60 lines, 2000 chars
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class GroceryItem:
    id: str
    name: str
    quantity: str
    checked: bool
    added_by: str
    created_at: datetime
    category: GroceryCategory = "other"


@dataclass(frozen=True)
class Meal:
    id: str
    day: date
    slot: MealSlot
    title: str
    ingredients: str  # one ingredient per line, max ~40 lines
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class Bill:
    id: str
    name: str
    amount_cents: int  # integer cents, 0..100_000_000
    due_date: date
    recurrence: BillRecurrence
    last_paid_on: date | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class Note:
    id: str
    title: str
    body: str  # max 5000 chars
    pinned: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StorageUsage:
    used_bytes: int
    limit_bytes: int  # 500 MB on the Supabase free tier (constant for SQLite dev)


class Repository(Protocol):
    """Bound to one authenticated user."""

    # --- tasks -----------------------------------------------------------
    def list_tasks(self, include_done: bool = False, limit: int = DEFAULT_LIMIT) -> list[Task]: ...
    def list_done_tasks(self, since: datetime, limit: int = DEFAULT_LIMIT) -> list[Task]:
        """Done, non-archived tasks completed at/after `since`, newest first."""
        ...
    def add_task(
        self,
        title: str,
        assignee: Assignee = "either",
        due_date: date | None = None,
        recurrence: Recurrence = "none",
        notes: str = "",
        priority: Priority = "normal",
        rotate: bool = False,
    ) -> Task: ...
    def update_task(self, task_id: str, **fields: object) -> Task: ...
    def complete_task(self, task_id: str) -> Task:
        """Marks done; if recurrence != 'none', also creates the next open occurrence
        (rolled forward to >= today; swaps assignee nick<->natalie when rotate)."""
        ...
    def reopen_task(self, task_id: str) -> Task: ...
    def archive_task(self, task_id: str) -> None: ...
    def list_archived_tasks(self, limit: int = DEFAULT_LIMIT) -> list[Task]: ...
    def restore_task(self, task_id: str) -> Task: ...

    # --- grocery ---------------------------------------------------------
    def list_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]: ...
    def add_grocery(
        self, name: str, quantity: str = "", category: GroceryCategory = "other"
    ) -> GroceryItem: ...
    def update_grocery(self, item_id: str, **fields: object) -> GroceryItem:
        """Editable: name, quantity, category."""
        ...
    def set_grocery_checked(self, item_id: str, checked: bool) -> GroceryItem: ...
    def archive_checked_grocery(self) -> int:
        """Archives (never deletes) all checked items; returns count."""
        ...
    def list_archived_grocery(self, limit: int = DEFAULT_LIMIT) -> list[GroceryItem]: ...
    def restore_grocery(self, item_id: str) -> GroceryItem: ...
    def frequent_grocery(self, limit: int = 12) -> list[tuple[str, GroceryCategory]]:
        """Most frequently added item names (incl. archived), with their latest category.
        Scans at most the newest 500 rows."""
        ...

    # --- meals -----------------------------------------------------------
    def list_meals(self, start: date, end: date, limit: int = DEFAULT_LIMIT) -> list[Meal]: ...
    def add_meal(
        self, day: date, title: str, ingredients: str = "", slot: MealSlot = "dinner"
    ) -> Meal: ...
    def update_meal(self, meal_id: str, **fields: object) -> Meal: ...
    def archive_meal(self, meal_id: str) -> None: ...
    def meal_to_grocery(self, meal_id: str) -> int:
        """Adds each ingredient line as a grocery item (category 'other'), skipping names
        already on the active list (case-insensitive). Returns number added."""
        ...

    # --- bills -----------------------------------------------------------
    def list_bills(self, limit: int = DEFAULT_LIMIT) -> list[Bill]: ...
    def add_bill(
        self,
        name: str,
        amount_cents: int,
        due_date: date,
        recurrence: BillRecurrence = "monthly",
    ) -> Bill: ...
    def update_bill(self, bill_id: str, **fields: object) -> Bill: ...
    def mark_bill_paid(self, bill_id: str) -> Bill:
        """Sets last_paid_on=today; a recurring bill's due_date advances to the next
        occurrence after today. A one-off bill keeps its due_date (paid = last_paid_on set)."""
        ...
    def archive_bill(self, bill_id: str) -> None: ...

    # --- notes -----------------------------------------------------------
    def list_notes(self, limit: int = DEFAULT_LIMIT) -> list[Note]:
        """Pinned first, then most recently updated."""
        ...
    def add_note(self, title: str, body: str = "", pinned: bool = False) -> Note: ...
    def update_note(self, note_id: str, **fields: object) -> Note: ...
    def archive_note(self, note_id: str) -> None: ...

    # --- subtasks --------------------------------------------------------
    def list_subtasks(self, task_ids: list[str]) -> list[Subtask]:
        """All non-archived subtasks for the given tasks in ONE query (no N+1); oldest first."""
        ...
    def add_subtask(self, task_id: str, title: str) -> Subtask: ...
    def set_subtask_done(self, subtask_id: str, done: bool) -> Subtask: ...
    def archive_subtask(self, subtask_id: str) -> None: ...

    # --- expenses (who owes whom) -----------------------------------------
    def list_expenses(self, since: date | None = None, limit: int = DEFAULT_LIMIT) -> list[Expense]:
        """Newest first. Balance maths lives in core.rules.expense_balance_cents."""
        ...
    def add_expense(
        self,
        day: date,
        description: str,
        amount_cents: int,
        paid_by: Person,
        split: ExpenseSplit = "equal",
        kind: ExpenseKind = "expense",
    ) -> Expense: ...
    def archive_expense(self, expense_id: str) -> None: ...

    # --- templates (shopping lists + recipes) ---------------------------------
    def list_templates(
        self, kind: TemplateKind | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Template]: ...
    def add_template(self, kind: TemplateKind, name: str, items: str) -> Template: ...
    def update_template(self, template_id: str, **fields: object) -> Template: ...
    def archive_template(self, template_id: str) -> None: ...
    def template_to_grocery(self, template_id: str) -> int:
        """Like meal_to_grocery: adds each line to the grocery list, skipping names already
        on the active list (case-insensitive). Returns number added."""
        ...

    # --- people & export --------------------------------------------------
    def list_members(self) -> dict[str, Person]:
        """user id -> 'nick'/'natalie' (from household_members; SQLite dev: fixed map)."""
        ...
    def export_rows(self, table: str, limit: int = 5000) -> list[dict[str, object]]:
        """All rows INCLUDING archived, JSON/CSV-friendly values (ISO strings), for the
        'Download my data' button. `table` must be one of EXPORT_TABLES, else ValidationError."""
        ...

    # --- storage meter ---------------------------------------------------
    def storage_usage(self) -> StorageUsage: ...
