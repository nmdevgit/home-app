"""Backend-independent business rules: validation and recurrence maths.

Kept separate so SQLite and Supabase repos enforce identical behaviour.
"""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from typing import get_args

from core import clock
from core.errors import ValidationError
from core.repo import Assignee, Recurrence

MAX_TITLE = 200
MAX_NOTES = 2000
MAX_GROCERY_NAME = 200
MAX_QUANTITY = 100

ASSIGNEES: frozenset[str] = frozenset(get_args(Assignee))
RECURRENCES: frozenset[str] = frozenset(get_args(Recurrence))
# Fields update_task may change; everything else is immutable or system-managed.
UPDATABLE_TASK_FIELDS: frozenset[str] = frozenset(
    {"title", "notes", "assignee", "due_date", "recurrence"}
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def clean_text(value: object, field: str, max_len: int, required: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    text = value.strip()
    if required and not text:
        raise ValidationError(f"{field} must not be empty")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters")
    return text


def clean_choice(value: object, field: str, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValidationError(f"{field} must be one of {sorted(allowed)}")
    return value


def clean_due_date(value: object) -> date | None:
    if value is None:
        return None
    # datetime is a date subclass; accepting it would silently store a time part.
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValidationError("due_date must be a date or None")
    return value


def validate_task_fields(fields: dict[str, object]) -> dict[str, object]:
    """Validate a partial set of task fields; returns cleaned copies."""
    unknown = set(fields) - UPDATABLE_TASK_FIELDS
    if unknown:
        raise ValidationError(f"cannot update field(s): {sorted(unknown)}")
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "title":
            cleaned[key] = clean_text(value, "title", MAX_TITLE, required=True)
        elif key == "notes":
            cleaned[key] = clean_text(value, "notes", MAX_NOTES, required=False)
        elif key == "assignee":
            cleaned[key] = clean_choice(value, "assignee", ASSIGNEES)
        elif key == "recurrence":
            cleaned[key] = clean_choice(value, "recurrence", RECURRENCES)
        else:
            cleaned[key] = clean_due_date(value)
    return cleaned


def add_months(day: date, months: int) -> date:
    """Same day-of-month N months on, clamped (Jan 31 + 1 month -> Feb 28/29)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _step(base: date, recurrence: str, k: int) -> date:
    if recurrence == "daily":
        return base + timedelta(days=k)
    if recurrence == "weekly":
        return base + timedelta(days=7 * k)
    # Always step from the original date (not the previous result) so the
    # month-end clamp does not drift: Jan 31 -> Feb 28 -> Mar 31.
    return add_months(base, k)


def next_due_date(current: date | None, recurrence: str, today: date | None = None) -> date:
    """First occurrence (due + k*interval, k >= 1) that is on/after today in APP_TZ.

    Rolling forward stops a long-overdue chore from spawning a backlog of past-due
    copies. With no due date the base is today, so the result is today + interval.
    """
    if recurrence not in ("daily", "weekly", "monthly"):
        raise ValidationError(f"recurrence {recurrence!r} has no next occurrence")
    now = today or clock.today()
    base = current or now
    candidate = _step(base, recurrence, 1)
    k = 1
    while candidate < now:
        k += 1
        candidate = _step(base, recurrence, k)
    return candidate
