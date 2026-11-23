"""Shared contract between backend and frontend. PM-owned: change only via PM."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

Assignee = Literal["nick", "natalie", "either"]
Recurrence = Literal["none", "daily", "weekly", "monthly"]
TaskStatus = Literal["open", "done"]


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


@dataclass(frozen=True)
class GroceryItem:
    id: str
    name: str
    quantity: str
    checked: bool
    added_by: str
    created_at: datetime


class Repository(Protocol):
    """Bound to one authenticated user. There is NO hard delete anywhere:
    'archive_*' sets archived_at; archived rows are hidden from list_* but kept."""

    def list_tasks(self, include_done: bool = False) -> list[Task]: ...
    def add_task(
        self,
        title: str,
        assignee: Assignee = "either",
        due_date: date | None = None,
        recurrence: Recurrence = "none",
        notes: str = "",
    ) -> Task: ...
    def update_task(self, task_id: str, **fields: object) -> Task: ...
    def complete_task(self, task_id: str) -> Task:
        """Marks done; if recurrence != 'none', also creates the next open occurrence."""
        ...
    def reopen_task(self, task_id: str) -> Task: ...
    def archive_task(self, task_id: str) -> None: ...

    def list_grocery(self) -> list[GroceryItem]: ...
    def add_grocery(self, name: str, quantity: str = "") -> GroceryItem: ...
    def set_grocery_checked(self, item_id: str, checked: bool) -> GroceryItem: ...
    def archive_checked_grocery(self) -> int:
        """Archives (never deletes) all checked items; returns count."""
        ...
