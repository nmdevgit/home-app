"""Pure helpers to bucket and filter tasks (no Streamlit imports)."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

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
