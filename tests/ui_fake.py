"""Tiny in-memory Repository for UI tests (independent of the SQLite/Supabase backends)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.repo import Bill, GroceryItem, Meal, Note, StorageUsage, Task


def _now() -> datetime:
    return datetime.now(UTC)


class FakeRepo:
    def __init__(self) -> None:
        self.n = 0
        self.tasks: dict[str, Task] = {}
        self.archived_tasks: dict[str, Task] = {}
        self.grocery: dict[str, GroceryItem] = {}
        self.archived_grocery: dict[str, GroceryItem] = {}
        self.meals: dict[str, Meal] = {}
        self.bills: dict[str, Bill] = {}
        self.notes: dict[str, Note] = {}

    def _id(self) -> str:
        self.n += 1
        return f"id{self.n}"

    # tasks
    def list_tasks(self, include_done: bool = False, limit: int = 300) -> list[Task]:
        return [t for t in self.tasks.values() if include_done or t.status == "open"][:limit]

    def list_done_tasks(self, since: datetime, limit: int = 300) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == "done"][:limit]

    def add_task(self, title: str, assignee: str = "either", due_date: date | None = None,
                 recurrence: str = "none", notes: str = "", priority: str = "normal",
                 rotate: bool = False) -> Task:
        task = Task(self._id(), title, notes, assignee, due_date, recurrence, "open",  # type: ignore[arg-type]
                    "u", _now(), None, priority, rotate)  # type: ignore[arg-type]
        self.tasks[task.id] = task
        return task

    def update_task(self, task_id: str, **fields: Any) -> Task:
        from dataclasses import replace
        self.tasks[task_id] = replace(self.tasks[task_id], **fields)
        return self.tasks[task_id]

    def complete_task(self, task_id: str) -> Task:
        return self.update_task(task_id, status="done", completed_at=_now())

    def reopen_task(self, task_id: str) -> Task:
        return self.update_task(task_id, status="open", completed_at=None)

    def archive_task(self, task_id: str) -> None:
        self.archived_tasks[task_id] = self.tasks.pop(task_id)

    def list_archived_tasks(self, limit: int = 300) -> list[Task]:
        return list(self.archived_tasks.values())[:limit]

    def restore_task(self, task_id: str) -> Task:
        self.tasks[task_id] = self.archived_tasks.pop(task_id)
        return self.tasks[task_id]

    # grocery
    def list_grocery(self, limit: int = 300) -> list[GroceryItem]:
        return list(self.grocery.values())[:limit]

    def add_grocery(self, name: str, quantity: str = "", category: str = "other") -> GroceryItem:
        item = GroceryItem(self._id(), name, quantity, False, "u", _now(), category)  # type: ignore[arg-type]
        self.grocery[item.id] = item
        return item

    def update_grocery(self, item_id: str, **fields: Any) -> GroceryItem:
        from dataclasses import replace
        self.grocery[item_id] = replace(self.grocery[item_id], **fields)
        return self.grocery[item_id]

    def set_grocery_checked(self, item_id: str, checked: bool) -> GroceryItem:
        return self.update_grocery(item_id, checked=checked)

    def archive_checked_grocery(self) -> int:
        ids = [i for i, g in self.grocery.items() if g.checked]
        for i in ids:
            self.archived_grocery[i] = self.grocery.pop(i)
        return len(ids)

    def list_archived_grocery(self, limit: int = 300) -> list[GroceryItem]:
        return list(self.archived_grocery.values())[:limit]

    def restore_grocery(self, item_id: str) -> GroceryItem:
        self.grocery[item_id] = self.archived_grocery.pop(item_id)
        return self.grocery[item_id]

    def frequent_grocery(self, limit: int = 12) -> list[tuple[str, str]]:
        return [(g.name, g.category) for g in self.grocery.values()][:limit]

    # meals
    def list_meals(self, start: date, end: date, limit: int = 300) -> list[Meal]:
        return [m for m in self.meals.values() if start <= m.day <= end][:limit]

    def add_meal(self, day: date, title: str, ingredients: str = "", slot: str = "dinner") -> Meal:
        meal = Meal(self._id(), day, slot, title, ingredients, "u", _now())  # type: ignore[arg-type]
        self.meals[meal.id] = meal
        return meal

    def update_meal(self, meal_id: str, **fields: Any) -> Meal:
        from dataclasses import replace
        self.meals[meal_id] = replace(self.meals[meal_id], **fields)
        return self.meals[meal_id]

    def archive_meal(self, meal_id: str) -> None:
        self.meals.pop(meal_id)

    def meal_to_grocery(self, meal_id: str) -> int:
        lines = [x for x in self.meals[meal_id].ingredients.splitlines() if x.strip()]
        for line in lines:
            self.add_grocery(line.strip())
        return len(lines)

    # bills
    def list_bills(self, limit: int = 300) -> list[Bill]:
        return list(self.bills.values())[:limit]

    def add_bill(self, name: str, amount_cents: int, due_date: date,
                 recurrence: str = "monthly") -> Bill:
        bill = Bill(self._id(), name, amount_cents, due_date, recurrence, None, "u", _now())  # type: ignore[arg-type]
        self.bills[bill.id] = bill
        return bill

    def update_bill(self, bill_id: str, **fields: Any) -> Bill:
        from dataclasses import replace
        self.bills[bill_id] = replace(self.bills[bill_id], **fields)
        return self.bills[bill_id]

    def mark_bill_paid(self, bill_id: str) -> Bill:
        bill = self.bills[bill_id]
        return self.update_bill(bill_id, last_paid_on=date.today(),
                                due_date=bill.due_date + timedelta(days=30))

    def archive_bill(self, bill_id: str) -> None:
        self.bills.pop(bill_id)

    # notes
    def list_notes(self, limit: int = 300) -> list[Note]:
        return sorted(self.notes.values(), key=lambda n: not n.pinned)[:limit]

    def add_note(self, title: str, body: str = "", pinned: bool = False) -> Note:
        note = Note(self._id(), title, body, pinned, "u", _now(), _now())
        self.notes[note.id] = note
        return note

    def update_note(self, note_id: str, **fields: Any) -> Note:
        from dataclasses import replace
        self.notes[note_id] = replace(self.notes[note_id], **fields)
        return self.notes[note_id]

    def archive_note(self, note_id: str) -> None:
        self.notes.pop(note_id)

    def storage_usage(self) -> StorageUsage:
        return StorageUsage(450 * 1024 * 1024, 500 * 1024 * 1024)
