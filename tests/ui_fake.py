"""Tiny in-memory Repository for UI tests (independent of the SQLite/Supabase backends)."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from core.errors import NotFoundError, ValidationError
from core.repo import (
    Activity,
    ArchivedItem,
    Bill,
    EventItem,
    EventOccurrence,
    Expense,
    Goal,
    GoalMove,
    GroceryItem,
    Meal,
    Note,
    Prefs,
    SearchHit,
    StorageUsage,
    Subtask,
    Task,
    Template,
)


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
        self.subtasks: dict[str, Subtask] = {}
        self.expenses: dict[str, Expense] = {}
        self.templates: dict[str, Template] = {}
        self.events: dict[str, EventItem] = {}
        self.archived_events: dict[str, EventItem] = {}
        self.goals: dict[str, Goal] = {}
        self.goal_moves: dict[str, GoalMove] = {}
        self.prefs = Prefs()
        self.archived: dict[str, dict[str, Any]] = {
            "meal": {}, "bill": {}, "note": {}, "expense": {}, "template": {},
        }

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
        return self.update_task(task_id, status="done", completed_at=_now(), completed_by="u")

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

    def set_grocery_price(self, item_id: str, price_cents: int | None) -> GroceryItem:
        return self.update_grocery(item_id, price_cents=price_cents)

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
        self.archived["meal"][meal_id] = self.meals.pop(meal_id)

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
        self.archived["bill"][bill_id] = self.bills.pop(bill_id)

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
        self.archived["note"][note_id] = self.notes.pop(note_id)

    def storage_usage(self) -> StorageUsage:
        return StorageUsage(450 * 1024 * 1024, 500 * 1024 * 1024)

    # subtasks
    def list_subtasks(self, task_ids: list[str]) -> list[Subtask]:
        return [s for s in self.subtasks.values() if s.task_id in task_ids]

    def add_subtask(self, task_id: str, title: str) -> Subtask:
        sub = Subtask(self._id(), task_id, title, False, _now())
        self.subtasks[sub.id] = sub
        return sub

    def set_subtask_done(self, subtask_id: str, done: bool) -> Subtask:
        from dataclasses import replace
        self.subtasks[subtask_id] = replace(self.subtasks[subtask_id], done=done)
        return self.subtasks[subtask_id]

    def archive_subtask(self, subtask_id: str) -> None:
        self.subtasks.pop(subtask_id)

    # expenses
    def list_expenses(self, since: date | None = None, limit: int = 300) -> list[Expense]:
        return list(self.expenses.values())[:limit]

    def add_expense(self, day: date, description: str, amount_cents: int, paid_by: str,
                    split: str = "equal", kind: str = "expense") -> Expense:
        exp = Expense(self._id(), day, description, amount_cents, paid_by, split, kind,  # type: ignore[arg-type]
                      "u", _now())
        self.expenses[exp.id] = exp
        return exp

    def archive_expense(self, expense_id: str) -> None:
        self.archived["expense"][expense_id] = self.expenses.pop(expense_id)

    # templates
    def list_templates(self, kind: str | None = None, limit: int = 300) -> list[Template]:
        return [t for t in self.templates.values() if kind in (None, t.kind)][:limit]

    def add_template(self, kind: str, name: str, items: str) -> Template:
        tpl = Template(self._id(), kind, name, items, "u", _now())  # type: ignore[arg-type]
        self.templates[tpl.id] = tpl
        return tpl

    def update_template(self, template_id: str, **fields: Any) -> Template:
        from dataclasses import replace
        self.templates[template_id] = replace(self.templates[template_id], **fields)
        return self.templates[template_id]

    def archive_template(self, template_id: str) -> None:
        self.archived["template"][template_id] = self.templates.pop(template_id)

    def template_to_grocery(self, template_id: str) -> int:
        lines = [x for x in self.templates[template_id].items.splitlines() if x.strip()]
        for line in lines:
            self.add_grocery(line.strip())
        return len(lines)

    # permanent delete
    def delete_task(self, task_id: str) -> None:
        self.tasks.pop(task_id, None) or self.archived_tasks.pop(task_id)
        for sid in [s for s, x in self.subtasks.items() if x.task_id == task_id]:
            self.subtasks.pop(sid)

    def delete_subtask(self, subtask_id: str) -> None:
        self.subtasks.pop(subtask_id)

    def delete_grocery(self, item_id: str) -> None:
        self.grocery.pop(item_id, None) or self.archived_grocery.pop(item_id)

    def delete_checked_grocery(self) -> int:
        ids = [i for i, g in self.grocery.items() if g.checked]
        for i in ids:
            self.grocery.pop(i)
        return len(ids)

    def delete_meal(self, meal_id: str) -> None:
        self.meals.pop(meal_id)

    def delete_bill(self, bill_id: str) -> None:
        self.bills.pop(bill_id)

    def delete_note(self, note_id: str) -> None:
        self.notes.pop(note_id)

    def delete_expense(self, expense_id: str) -> None:
        self.expenses.pop(expense_id)

    def list_archived_items(self, limit: int = 300) -> list[ArchivedItem]:
        out = []
        buckets = {**self.archived, "event": self.archived_events}
        for kind, rows in buckets.items():
            for rid, row in rows.items():
                title = getattr(row, "title", None) or getattr(row, "name", None) or str(rid)
                out.append(ArchivedItem(kind, str(rid), str(title), "", _now()))  # type: ignore[arg-type]
        return out[:limit]

    def restore_item(self, kind: str, item_id: str) -> None:
        if kind not in ("meal", "bill", "note", "expense", "template", "event", "goal", "subtask"):
            raise ValidationError(f"unknown archived kind: {kind!r}")
        if kind in ("goal", "subtask"):
            raise NotFoundError(f"archived {kind} {item_id} not found")
        getattr(self, f"restore_{kind}")(item_id)

    def delete_template(self, template_id: str) -> None:
        self.templates.pop(template_id)

    def purge_archived(self) -> int:
        n = len(self.archived_tasks) + len(self.archived_grocery)
        self.archived_tasks.clear()
        self.archived_grocery.clear()
        return n

    # people and export
    def list_members(self) -> dict[str, str]:
        return {"u": "nick"}

    def export_rows(self, table: str, limit: int = 5000) -> list[dict[str, object]]:
        return [{"id": "1", "title": "=SUM(A1)"}] if table == "notes" else []

    # ---- round 4 -------------------------------------------------------------
    def list_activity(self, since: datetime, limit: int = 50) -> list[Activity]:
        out = [
            Activity(t.created_at, "nick", "added", "task", t.title, t.id)
            for t in self.tasks.values()
        ]
        return sorted(out, key=lambda a: a.at, reverse=True)[:limit]

    def search(self, query: str, limit: int = 40) -> list[SearchHit]:
        q = query.strip().lower()
        hits = [SearchHit("task", t.id, t.title, t.notes, "tasks") for t in self.tasks.values()
                if q in t.title.lower()]
        hits += [SearchHit("note", n.id, n.title, n.body, "notes") for n in self.notes.values()
                 if q in n.title.lower()]
        return hits[:limit]

    def bulk_complete_tasks(self, task_ids: list[str]) -> int:
        for i in task_ids:
            self.complete_task(i)
        return len(task_ids)

    def bulk_update_tasks(self, task_ids: list[str], **fields: Any) -> int:
        for i in task_ids:
            self.update_task(i, **fields)
        return len(task_ids)

    def bulk_archive_tasks(self, task_ids: list[str]) -> int:
        for i in task_ids:
            self.archive_task(i)
        return len(task_ids)

    def bulk_delete_tasks(self, task_ids: list[str]) -> int:
        for i in task_ids:
            self.delete_task(i)
        return len(task_ids)

    def undo_complete(self, task_id: str) -> Task:
        return self.reopen_task(task_id)

    def restore_meal(self, meal_id: str) -> Meal:
        return self.meals.setdefault(meal_id, self.archived["meal"].pop(meal_id))

    def restore_bill(self, bill_id: str) -> Bill:
        return self.bills.setdefault(bill_id, self.archived["bill"].pop(bill_id))

    def restore_note(self, note_id: str) -> Note:
        return self.notes.setdefault(note_id, self.archived["note"].pop(note_id))

    def restore_expense(self, expense_id: str) -> Expense:
        return self.expenses.setdefault(expense_id, self.archived["expense"].pop(expense_id))

    def restore_template(self, template_id: str) -> Template:
        return self.templates.setdefault(
            template_id, self.archived["template"].pop(template_id))

    # events
    def _occ(self, start: date, end: date) -> list[EventOccurrence]:
        return sorted(
            (EventOccurrence(e, e.day) for e in self.events.values() if start <= e.day <= end),
            key=lambda o: o.on)

    def list_events(self, start: date, end: date, limit: int = 300) -> list[EventOccurrence]:
        return self._occ(start, end)[:limit]

    def upcoming_events(
        self, today: date, days: int = 60, limit: int = 10
    ) -> list[EventOccurrence]:
        return self._occ(today, today + timedelta(days=days))[:limit]

    def add_event(self, title: str, day: date, who: str = "both", start_time: time | None = None,
                  notes: str = "", recurrence: str = "none", remind_days: int = 0) -> EventItem:
        ev = EventItem(self._id(), title, day, start_time, who, notes, recurrence,  # type: ignore[arg-type]
                       remind_days, "u", _now())
        self.events[ev.id] = ev
        return ev

    def update_event(self, event_id: str, **fields: Any) -> EventItem:
        self.events[event_id] = replace(self.events[event_id], **fields)
        return self.events[event_id]

    def archive_event(self, event_id: str) -> None:
        self.archived_events[event_id] = self.events.pop(event_id)

    def restore_event(self, event_id: str) -> EventItem:
        self.events[event_id] = self.archived_events.pop(event_id)
        return self.events[event_id]

    def delete_event(self, event_id: str) -> None:
        gone = self.events.pop(event_id, None) or self.archived_events.pop(event_id, None)
        if gone is None:
            raise NotFoundError(event_id)

    # goals
    def list_goals(self, limit: int = 50) -> list[Goal]:
        return list(self.goals.values())[:limit]

    def add_goal(self, name: str, target_cents: int, due_date: date | None = None,
                 icon: str = "savings") -> Goal:
        goal = Goal(self._id(), name, target_cents, due_date, icon, 0, "u", _now())
        self.goals[goal.id] = goal
        return goal

    def update_goal(self, goal_id: str, **fields: Any) -> Goal:
        self.goals[goal_id] = replace(self.goals[goal_id], **fields)
        return self.goals[goal_id]

    def archive_goal(self, goal_id: str) -> None:
        self.goals.pop(goal_id)

    def delete_goal(self, goal_id: str) -> None:
        self.goals.pop(goal_id)
        for mid in [m for m, x in self.goal_moves.items() if x.goal_id == goal_id]:
            self.goal_moves.pop(mid)

    def add_goal_move(self, goal_id: str, amount_cents: int, person: str,
                      note: str = "") -> GoalMove:
        move = GoalMove(self._id(), goal_id, amount_cents, person, date.today(), note, _now())  # type: ignore[arg-type]
        self.goal_moves[move.id] = move
        goal = self.goals[goal_id]
        self.goals[goal_id] = replace(goal, saved_cents=goal.saved_cents + amount_cents)
        return move

    def list_goal_moves(self, goal_id: str, limit: int = 50) -> list[GoalMove]:
        return [m for m in self.goal_moves.values() if m.goal_id == goal_id][:limit]

    def delete_goal_move(self, move_id: str) -> None:
        move = self.goal_moves.pop(move_id)
        goal = self.goals[move.goal_id]
        self.goals[move.goal_id] = replace(goal, saved_cents=goal.saved_cents - move.amount_cents)

    # prefs
    def get_prefs(self) -> Prefs:
        return self.prefs

    def save_prefs(self, **fields: Any) -> Prefs:
        self.prefs = replace(self.prefs, **fields)
        return self.prefs
