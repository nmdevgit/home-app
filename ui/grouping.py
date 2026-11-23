"""Pure helpers to bucket and filter tasks (no Streamlit imports)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from core.repo import Task

PEOPLE = ("nick", "natalie")


def partner_of(me: str) -> str:
    """Return the other person's key."""
    return "natalie" if me == "nick" else "nick"


def bucket_of(task: Task, today: date, horizon_days: int = 7) -> str | None:
    """Classify an open task: overdue / today / upcoming, else None."""
    if task.status != "open" or task.due_date is None:
        return None
    if task.due_date < today:
        return "overdue"
    if task.due_date == today:
        return "today"
    if task.due_date <= today + timedelta(days=horizon_days):
        return "upcoming"
    return None


def group_by_owner(tasks: Iterable[Task], me: str) -> dict[str, list[Task]]:
    """Group into mine / partner / either, each sorted by due date then title."""
    groups: dict[str, list[Task]] = {"mine": [], "partner": [], "either": []}
    for task in tasks:
        if task.assignee == "either":
            groups["either"].append(task)
        elif task.assignee == me:
            groups["mine"].append(task)
        else:
            groups["partner"].append(task)
    for items in groups.values():
        items.sort(key=lambda t: (t.due_date or date.max, t.title.lower()))
    return groups


def filter_tasks(tasks: Iterable[Task], me: str, mine_only: bool, show_done: bool) -> list[Task]:
    """Apply the Tasks page filters. 'Mine' includes tasks assigned to either."""
    out = []
    for task in tasks:
        if mine_only and task.assignee not in (me, "either"):
            continue
        if (task.status == "done") != show_done:
            continue
        out.append(task)
    out.sort(key=lambda t: (t.due_date or date.max, t.title.lower()))
    return out


PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
CATEGORY_ORDER = (
    "produce", "dairy", "meat", "bakery", "pantry", "frozen", "drinks", "household", "other",
)


def search_tasks(tasks: Iterable[Task], query: str) -> list[Task]:
    """Case-insensitive match on title or notes; empty query keeps everything."""
    needle = query.strip().lower()
    if not needle:
        return list(tasks)
    return [t for t in tasks if needle in t.title.lower() or needle in t.notes.lower()]


def sort_tasks(tasks: Iterable[Task]) -> list[Task]:
    """Due date first (undated last), then priority high->low, then title."""
    return sorted(
        tasks,
        key=lambda t: (t.due_date or date.max, PRIORITY_RANK.get(t.priority, 1), t.title.lower()),
    )


def group_grocery(items: Iterable[Any]) -> dict[str, list[Any]]:
    """Group grocery items by category (fixed order); unchecked first, then by age."""
    groups: dict[str, list[Any]] = {}
    for item in sorted(items, key=lambda i: (i.checked, i.created_at)):
        groups.setdefault(item.category, []).append(item)
    order = {c: n for n, c in enumerate(CATEGORY_ORDER)}
    return dict(sorted(groups.items(), key=lambda kv: order.get(kv[0], len(order))))


def week_start(day: date) -> date:
    """Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def bill_status(due: date, today: date, paid_on: date | None = None) -> str:
    """'paid' (one-off paid), 'overdue', 'soon' (within 7 days) or 'later'."""
    if paid_on is not None and paid_on >= due:
        return "paid"
    if due < today:
        return "overdue"
    if due <= today + timedelta(days=7):
        return "soon"
    return "later"
