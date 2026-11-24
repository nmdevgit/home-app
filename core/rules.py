"""Backend-independent business rules: validation and recurrence maths.

Kept separate so SQLite and Supabase repos enforce identical behaviour.
"""
from __future__ import annotations

import calendar
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, get_args

from core import clock
from core.errors import ValidationError
from core.repo import (
    EXPORT_TABLES,
    GOAL_ICONS,
    Accent,
    Assignee,
    BillRecurrence,
    EventRecurrence,
    EventWho,
    Expense,
    ExpenseKind,
    ExpenseSplit,
    GroceryCategory,
    GroceryItem,
    MealSlot,
    Person,
    Priority,
    Recurrence,
    TemplateKind,
)

if TYPE_CHECKING:
    from core.repo import Goal

MAX_TITLE = 200
MAX_NOTES = 2000
MAX_GROCERY_NAME = 200
MAX_QUANTITY = 100
MAX_NOTE_BODY = 5000
MAX_INGREDIENT_LINES = 40
MAX_INGREDIENT_CHARS = 2000
MAX_AMOUNT_CENTS = 100_000_000
MIN_LIMIT = 1
MAX_LIMIT = 500
MAX_EXPORT_LIMIT = 5000
MAX_SUBTASK_TITLE = 200
MAX_SUBTASK_TASK_IDS = 200  # one IN(...) query; keeps the PostgREST URL short
MAX_SUBTASKS = 2000
MAX_EXPENSE_DESCRIPTION = 200
MAX_TEMPLATE_NAME = 100
MAX_TEMPLATE_LINES = 60
MAX_TEMPLATE_CHARS = 2000
MAX_TEMPLATE_LINE = 200

ASSIGNEES: frozenset[str] = frozenset(get_args(Assignee))
RECURRENCES: frozenset[str] = frozenset(get_args(Recurrence))
PRIORITIES: frozenset[str] = frozenset(get_args(Priority))
GROCERY_CATEGORIES: frozenset[str] = frozenset(get_args(GroceryCategory))
MEAL_SLOTS: frozenset[str] = frozenset(get_args(MealSlot))
BILL_RECURRENCES: frozenset[str] = frozenset(get_args(BillRecurrence))
PEOPLE: frozenset[str] = frozenset(get_args(Person))
EXPENSE_SPLITS: frozenset[str] = frozenset(get_args(ExpenseSplit))
EXPENSE_KINDS: frozenset[str] = frozenset(get_args(ExpenseKind))
TEMPLATE_KINDS: frozenset[str] = frozenset(get_args(TemplateKind))
SLOT_ORDER: dict[str, int] = {"breakfast": 0, "lunch": 1, "dinner": 2}
# Fields update_task may change; everything else is immutable or system-managed.
UPDATABLE_TASK_FIELDS: frozenset[str] = frozenset(
    {"title", "notes", "assignee", "due_date", "recurrence", "priority", "rotate"}
)
UPDATABLE_GROCERY_FIELDS: frozenset[str] = frozenset(
    {"name", "quantity", "category", "price_cents"}
)
UPDATABLE_MEAL_FIELDS: frozenset[str] = frozenset({"day", "slot", "title", "ingredients"})
UPDATABLE_BILL_FIELDS: frozenset[str] = frozenset(
    {"name", "amount_cents", "due_date", "recurrence"}
)
UPDATABLE_NOTE_FIELDS: frozenset[str] = frozenset({"title", "body", "pinned"})
UPDATABLE_TEMPLATE_FIELDS: frozenset[str] = frozenset({"name", "items"})


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
        elif key == "priority":
            cleaned[key] = clean_choice(value, "priority", PRIORITIES)
        elif key == "rotate":
            cleaned[key] = clean_bool(value, "rotate")
        else:
            cleaned[key] = clean_due_date(value)
    return cleaned


def clamp_limit(limit: object) -> int:
    """Clamp a caller-supplied page size to 1..500 (free-tier memory guard)."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError("limit must be a whole number")
    return max(MIN_LIMIT, min(MAX_LIMIT, limit))


def clean_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be true or false")
    return value


def clean_required_date(value: object, field: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValidationError(f"{field} must be a date")
    return value


def clean_amount_cents(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("amount_cents must be a whole number of cents")
    if not 0 <= value <= MAX_AMOUNT_CENTS:
        raise ValidationError(f"amount_cents must be between 0 and {MAX_AMOUNT_CENTS}")
    return value


def clean_ingredients(value: object) -> str:
    """One ingredient per line; blank lines dropped; <=40 lines, <=2000 chars."""
    text = clean_text(value, "ingredients", 10 * MAX_INGREDIENT_CHARS, required=False)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > MAX_INGREDIENT_LINES:
        raise ValidationError(f"ingredients must have at most {MAX_INGREDIENT_LINES} lines")
    if any(len(line) > MAX_GROCERY_NAME for line in lines):
        raise ValidationError(f"each ingredient must be at most {MAX_GROCERY_NAME} characters")
    joined = "\n".join(lines)
    if len(joined) > MAX_INGREDIENT_CHARS:
        raise ValidationError(f"ingredients must be at most {MAX_INGREDIENT_CHARS} characters")
    return joined


def clamp_export_limit(limit: object) -> int:
    """Clamp an export page size to 1..5000."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValidationError("limit must be a whole number")
    return max(MIN_LIMIT, min(MAX_EXPORT_LIMIT, limit))


def clean_subtask_title(value: object) -> str:
    return clean_text(value, "title", MAX_SUBTASK_TITLE, required=True)


def clean_task_ids(task_ids: object) -> list[str]:
    """Distinct, non-empty string ids (order kept), capped at MAX_SUBTASK_TASK_IDS."""
    if isinstance(task_ids, str) or not isinstance(task_ids, list | tuple | set | frozenset):
        raise ValidationError("task_ids must be a list of ids")
    out: list[str] = []
    for item in task_ids:
        if not isinstance(item, str) or not item:
            raise ValidationError("task ids must be non-empty text")
        if item not in out:
            out.append(item)
    return out[:MAX_SUBTASK_TASK_IDS]


def validate_expense(
    day: object,
    description: object,
    amount_cents: object,
    paid_by: object,
    split: object,
    kind: object,
) -> dict[str, object]:
    """Validate a new expense/settlement; amount must be 1..100_000_000 cents."""
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise ValidationError("amount_cents must be a whole number of cents")
    if not 1 <= amount_cents <= MAX_AMOUNT_CENTS:
        raise ValidationError(f"amount_cents must be between 1 and {MAX_AMOUNT_CENTS}")
    return {
        "day": clean_required_date(day, "day"),
        "description": clean_text(description, "description", MAX_EXPENSE_DESCRIPTION, True),
        "amount_cents": amount_cents,
        "paid_by": clean_choice(paid_by, "paid_by", PEOPLE),
        "split": clean_choice(split, "split", EXPENSE_SPLITS),
        "kind": clean_choice(kind, "kind", EXPENSE_KINDS),
    }


def clean_template_items(value: object) -> str:
    """One item per line; blank lines dropped; <=60 lines, <=200 chars/line, <=2000 total."""
    text = clean_text(value, "items", 10 * MAX_TEMPLATE_CHARS, required=False)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > MAX_TEMPLATE_LINES:
        raise ValidationError(f"items must have at most {MAX_TEMPLATE_LINES} lines")
    if any(len(line) > MAX_TEMPLATE_LINE for line in lines):
        raise ValidationError(f"each item must be at most {MAX_TEMPLATE_LINE} characters")
    joined = "\n".join(lines)
    if len(joined) > MAX_TEMPLATE_CHARS:
        raise ValidationError(f"items must be at most {MAX_TEMPLATE_CHARS} characters")
    return joined


def validate_template_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_TEMPLATE_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "name":
            cleaned[key] = clean_text(value, "name", MAX_TEMPLATE_NAME, required=True)
        else:
            cleaned[key] = clean_template_items(value)
    return cleaned


def export_value(value: object) -> object:
    """Convert a DB value to a JSON/CSV-friendly primitive (dates -> ISO strings)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def clean_export_table(table: object) -> str:
    if not isinstance(table, str) or table not in EXPORT_TABLES:
        raise ValidationError(f"table must be one of {list(EXPORT_TABLES)}")
    return table


def _reject_unknown(fields: dict[str, object], allowed: frozenset[str]) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValidationError(f"cannot update field(s): {sorted(unknown)}")


def clean_price_cents(value: object) -> int | None:
    """Grocery line price: None clears it, else an int 0..MAX_AMOUNT_CENTS (bools rejected)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("price_cents must be a whole number of cents")
    if not 0 <= value <= MAX_AMOUNT_CENTS:
        raise ValidationError(f"price_cents must be between 0 and {MAX_AMOUNT_CENTS}")
    return value


def cart_total_cents(items: Iterable[GroceryItem]) -> int:
    """Sum of price_cents over checked items that have a price."""
    return sum(i.price_cents for i in items if i.checked and i.price_cents is not None)


def validate_grocery_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_GROCERY_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "name":
            cleaned[key] = clean_text(value, "name", MAX_GROCERY_NAME, required=True)
        elif key == "quantity":
            cleaned[key] = clean_text(value, "quantity", MAX_QUANTITY, required=False)
        elif key == "price_cents":
            cleaned[key] = clean_price_cents(value)
        else:
            cleaned[key] = clean_choice(value, "category", GROCERY_CATEGORIES)
    return cleaned


def validate_meal_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_MEAL_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "day":
            cleaned[key] = clean_required_date(value, "day")
        elif key == "slot":
            cleaned[key] = clean_choice(value, "slot", MEAL_SLOTS)
        elif key == "title":
            cleaned[key] = clean_text(value, "title", MAX_TITLE, required=True)
        else:
            cleaned[key] = clean_ingredients(value)
    return cleaned


def validate_bill_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_BILL_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "name":
            cleaned[key] = clean_text(value, "name", MAX_TITLE, required=True)
        elif key == "amount_cents":
            cleaned[key] = clean_amount_cents(value)
        elif key == "due_date":
            cleaned[key] = clean_required_date(value, "due_date")
        else:
            cleaned[key] = clean_choice(value, "recurrence", BILL_RECURRENCES)
    return cleaned


def validate_note_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_NOTE_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "title":
            cleaned[key] = clean_text(value, "title", MAX_TITLE, required=True)
        elif key == "body":
            cleaned[key] = clean_text(value, "body", MAX_NOTE_BODY, required=False)
        else:
            cleaned[key] = clean_bool(value, "pinned")
    return cleaned


def swap_assignee(assignee: str) -> str:
    """Chore rotation: nick <-> natalie; 'either' is unchanged."""
    return {"nick": "natalie", "natalie": "nick"}.get(assignee, assignee)


def frequent_names(
    rows_newest_first: list[tuple[str, str]], limit: int
) -> list[tuple[str, str]]:
    """Count names case-insensitively; return (display name, category) most frequent first.

    Display name and category come from the newest row of each name; ties keep the
    more recently added name first.
    """
    counts: dict[str, int] = {}
    latest: dict[str, tuple[str, str]] = {}
    for name, category in rows_newest_first:
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
        latest.setdefault(key, (name, category))
    ranked = sorted(counts, key=lambda k: -counts[k])  # stable: keeps recency order
    return [latest[k] for k in ranked[: clamp_limit(limit)]]


def monthly_equivalent_cents(amount_cents: int, recurrence: str) -> int:
    """A bill's cost per month in cents, for the 'monthly total' figure.

    weekly -> amount*52/12, fortnightly -> amount*26/12, monthly -> amount,
    yearly -> amount/12, none -> 0 (a one-off is not a running monthly cost).
    Integer arithmetic, rounded half up (never floats, so totals are exact).
    """
    if recurrence not in BILL_RECURRENCES:
        raise ValidationError(f"unknown bill recurrence {recurrence!r}")
    if recurrence == "weekly":
        return (amount_cents * 52 + 6) // 12
    if recurrence == "fortnightly":
        return (amount_cents * 26 + 6) // 12
    if recurrence == "monthly":
        return amount_cents
    if recurrence == "yearly":
        return (amount_cents + 6) // 12
    return 0


def next_bill_due(current: date, recurrence: str, today: date | None = None) -> date:
    """Next due date strictly after today (k >= 1 steps from the current due date).

    'none' keeps the due date. Steps always start from the original date so the
    month-end clamp does not drift (Jan 31 -> Feb 28 -> Mar 31).
    """
    if recurrence == "none":
        return current
    if recurrence not in BILL_RECURRENCES:
        raise ValidationError(f"unknown bill recurrence {recurrence!r}")
    now = today or clock.today()
    k = 1
    while (candidate := _bill_step(current, recurrence, k)) <= now:
        k += 1
    return candidate


def _bill_step(base: date, recurrence: str, k: int) -> date:
    if recurrence == "weekly":
        return base + timedelta(days=7 * k)
    if recurrence == "fortnightly":
        return base + timedelta(days=14 * k)
    if recurrence == "monthly":
        return add_months(base, k)
    return add_months(base, 12 * k)


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


def expense_balance_cents(expenses: Iterable[Expense]) -> int:
    """Net balance in cents: positive = natalie owes nick, negative = nick owes natalie.

    Per expense (amount A, payer P; the other person is O):
      equal       O owes P half, rounded half up: (A + 1) // 2 (an odd cent goes to the
                  payer's favour; computed on the positive amount so it is symmetric)
      payer_only  no debt
      other_only  O owes P the full A
      settlement  P handed O the full A: counts like other_only (P is owed A more /
                  owes A less); the split field is ignored
    Archived rows are the caller's concern (list_expenses already hides them).
    """
    total = 0
    for exp in expenses:
        if exp.kind == "settlement" or exp.split == "other_only":
            owed = exp.amount_cents
        elif exp.split == "equal":
            owed = (exp.amount_cents + 1) // 2
        else:
            owed = 0
        total += owed if exp.paid_by == "nick" else -owed
    return total


# ---- round 4: search, bulk, events, goals, prefs -------------------------------------
MIN_SEARCH = 2
MAX_SEARCH = 60
MAX_BULK_IDS = 50
MAX_EVENT_TITLE = 120
MAX_EVENT_NOTES = 1000
MAX_REMIND_DAYS = 60
MAX_OCCURRENCES = 400  # hard cap on one event's expansion inside a window
MAX_GOAL_NAME = 80
MAX_GOAL_TARGET_CENTS = 1_000_000_000
MAX_GOAL_NOTE = 120
MAX_PINNED = 6
MAX_GOAL_MOVES_SUM = 10_000  # rows read when summing a goal's moves
SEARCH_PER_SOURCE = 8
SEARCH_SNIPPET = 80
# Characters that are special in PostgREST or=/ilike filters or in SQL LIKE (plus the
# double quote we use to wrap values). They are removed from the query, never escaped.
_SEARCH_STRIP = re.compile(r'[,()*%_\\"]')

EVENT_WHO: frozenset[str] = frozenset(get_args(EventWho))
EVENT_RECURRENCES: frozenset[str] = frozenset(get_args(EventRecurrence))
ACCENTS: frozenset[str] = frozenset(get_args(Accent))
GOAL_ICON_SET: frozenset[str] = frozenset(GOAL_ICONS)
# url_paths a person may pin or start on (kept in sync with ui/nav.PAGES by hand).
PAGE_KEYS: frozenset[str] = frozenset(
    {
        "today", "tasks", "grocery", "agenda", "calendar", "meals", "bills", "expenses",
        "goals", "templates", "notes", "more", "stats", "activity", "search", "archive",
        "settings",
    }
)
UPDATABLE_EVENT_FIELDS: frozenset[str] = frozenset(
    {"title", "day", "start_time", "who", "notes", "recurrence", "remind_days"}
)
UPDATABLE_GOAL_FIELDS: frozenset[str] = frozenset({"name", "target_cents", "due_date", "icon"})
BULK_TASK_FIELDS: frozenset[str] = frozenset({"assignee", "due_date", "priority"})
PREF_FIELDS: frozenset[str] = frozenset({"accent", "pinned", "start_page", "compact"})


def sanitize_search(query: object) -> str:
    """Validate (stripped, 2..60 chars) then remove filter-special characters.

    Raises ValidationError when the stripped query is too short/long or nothing is left
    after sanitising. The result is safe to splice into a PostgREST filter or LIKE pattern.
    """
    text = clean_text(query, "query", MAX_SEARCH, required=True)
    if len(text) < MIN_SEARCH:
        raise ValidationError(f"query must be at least {MIN_SEARCH} characters")
    cleaned = " ".join(_SEARCH_STRIP.sub("", text).split())
    if not cleaned:
        raise ValidationError("query has no searchable characters")
    return cleaned


def snippet(text: str, limit: int = SEARCH_SNIPPET) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "\u2026"


def clean_bulk_ids(ids: object) -> list[str]:
    """Distinct non-empty string ids, order kept; more than 50 is a ValidationError."""
    if isinstance(ids, str) or not isinstance(ids, list | tuple | set | frozenset):
        raise ValidationError("ids must be a list of ids")
    out: list[str] = []
    for item in ids:
        if not isinstance(item, str) or not item:
            raise ValidationError("ids must be non-empty text")
        if item not in out:
            out.append(item)
    if len(out) > MAX_BULK_IDS:
        raise ValidationError(f"at most {MAX_BULK_IDS} items at a time")
    return out


def validate_bulk_task_fields(fields: dict[str, object]) -> dict[str, object]:
    if not fields:
        raise ValidationError("nothing to update")
    _reject_unknown(fields, BULK_TASK_FIELDS)
    return validate_task_fields(fields)


def clean_time(value: object, field: str = "start_time") -> time | None:
    if value is None:
        return None
    if isinstance(value, datetime) or not isinstance(value, time):
        raise ValidationError(f"{field} must be a time or None")
    return value.replace(second=0, microsecond=0, tzinfo=None)


def clean_int_range(value: object, field: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be a whole number")
    if not low <= value <= high:
        raise ValidationError(f"{field} must be between {low} and {high}")
    return value


def validate_event_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_EVENT_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "title":
            cleaned[key] = clean_text(value, "title", MAX_EVENT_TITLE, required=True)
        elif key == "day":
            cleaned[key] = clean_required_date(value, "day")
        elif key == "start_time":
            cleaned[key] = clean_time(value)
        elif key == "who":
            cleaned[key] = clean_choice(value, "who", EVENT_WHO)
        elif key == "notes":
            cleaned[key] = clean_text(value, "notes", MAX_EVENT_NOTES, required=False)
        elif key == "recurrence":
            cleaned[key] = clean_choice(value, "recurrence", EVENT_RECURRENCES)
        else:
            cleaned[key] = clean_int_range(value, "remind_days", 0, MAX_REMIND_DAYS)
    return cleaned


def validate_goal_fields(fields: dict[str, object]) -> dict[str, object]:
    _reject_unknown(fields, UPDATABLE_GOAL_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "name":
            cleaned[key] = clean_text(value, "name", MAX_GOAL_NAME, required=True)
        elif key == "target_cents":
            cleaned[key] = clean_int_range(value, "target_cents", 1, MAX_GOAL_TARGET_CENTS)
        elif key == "due_date":
            cleaned[key] = clean_due_date(value)
        else:
            cleaned[key] = clean_choice(value, "icon", GOAL_ICON_SET)
    return cleaned


def validate_goal_move(amount_cents: object, person: object, note: object) -> dict[str, object]:
    big = MAX_GOAL_TARGET_CENTS
    amount = clean_int_range(amount_cents, "amount_cents", -big, big)
    if amount == 0:
        raise ValidationError("amount_cents must not be zero")
    return {
        "amount_cents": amount,
        "person": clean_choice(person, "person", PEOPLE),
        "note": clean_text(note, "note", MAX_GOAL_NOTE, required=False),
    }


def validate_prefs(fields: dict[str, object]) -> dict[str, object]:
    """Validated partial prefs. `pinned` becomes a de-duplicated tuple of page keys."""
    _reject_unknown(fields, PREF_FIELDS)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "accent":
            cleaned[key] = clean_choice(value, "accent", ACCENTS)
        elif key == "start_page":
            cleaned[key] = clean_choice(value, "start_page", PAGE_KEYS)
        elif key == "compact":
            cleaned[key] = clean_bool(value, "compact")
        else:
            if isinstance(value, str) or not isinstance(value, list | tuple):
                raise ValidationError("pinned must be a list of pages")
            pins: list[str] = []
            for item in value:
                page = clean_choice(item, "pinned page", PAGE_KEYS)
                if page not in pins:
                    pins.append(page)
            if len(pins) > MAX_PINNED:
                raise ValidationError(f"pin at most {MAX_PINNED} pages")
            cleaned[key] = tuple(pins)
    return cleaned


def parse_pinned(text: str | None) -> tuple[str, ...]:
    """Stored csv -> known page keys only (ignores junk written by hand)."""
    pins = [p for p in (text or "").split(",") if p in PAGE_KEYS]
    return tuple(dict.fromkeys(pins))[:MAX_PINNED]


def _yearly(anchor: date, year: int) -> date:
    # Feb 29 anniversaries fall on Feb 28 in non-leap years.
    return date(year, anchor.month, min(anchor.day, calendar.monthrange(year, anchor.month)[1]))


def event_occurrences(event: object, start: date, end: date) -> list[date]:
    """Dates within [start, end] on which `event` (needs .day and .recurrence) falls.

    Never earlier than the anchor day; at most MAX_OCCURRENCES results; cost is
    proportional to the results, not to how far in the past the anchor is.
    """
    anchor: date = event.day  # type: ignore[attr-defined]
    recurrence: str = event.recurrence  # type: ignore[attr-defined]
    if recurrence == "none":
        return [anchor] if start <= anchor <= end else []
    start = max(start, anchor)
    if end < start:
        return []
    out: list[date] = []
    if recurrence == "weekly":
        k = -(-(start - anchor).days // 7)
        while len(out) < MAX_OCCURRENCES and (d := anchor + timedelta(days=7 * k)) <= end:
            out.append(d)
            k += 1
    elif recurrence == "monthly":
        months = (start.year - anchor.year) * 12 + start.month - anchor.month
        k = max(0, months)
        while len(out) < MAX_OCCURRENCES and (d := add_months(anchor, k)) <= end:
            if d >= start:
                out.append(d)
            k += 1
    elif recurrence == "yearly":
        year = start.year
        while len(out) < MAX_OCCURRENCES and year <= min(end.year, date.max.year):
            d = _yearly(anchor, year)
            if start <= d <= end:
                out.append(d)
            year += 1
    else:
        raise ValidationError(f"unknown event recurrence {recurrence!r}")
    return out


def goal_pace(goal: Goal, today: date) -> int:
    """Cents per week still needed to hit the target by the due date (0 if reached or no
    due date; the whole remainder if the due date is today or past)."""
    remaining = goal.target_cents - goal.saved_cents
    if remaining <= 0 or goal.due_date is None:
        return 0
    days = (goal.due_date - today).days
    if days <= 0:
        return remaining
    weeks = -(-days // 7)
    return -(-remaining // weeks)


# ---- unified archive (list_archived_items / restore_item) --------------------------------
# kind -> (table, columns selected for the listing)
ARCHIVED_SOURCES: dict[str, tuple[str, str]] = {
    "meal": ("meals", "id, title, day, slot, archived_at"),
    "bill": ("bills", "id, name, amount_cents, due_date, archived_at"),
    "note": ("notes", "id, title, archived_at"),
    "expense": ("expenses", "id, description, amount_cents, day, archived_at"),
    "template": ("templates", "id, name, kind, archived_at"),
    "event": ("events", "id, title, day, archived_at"),
    "goal": ("goals", "id, name, target_cents, due_date, archived_at"),
    "subtask": ("subtasks", "id, title, done, archived_at"),
}


def check_archived_kind(kind: object) -> str:
    if not isinstance(kind, str) or kind not in ARCHIVED_SOURCES:
        raise ValidationError(f"unknown archived kind: {kind!r}")
    return kind


def money_text(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def archived_title_detail(kind: str, row: dict[str, object] | object) -> tuple[str, str]:
    """(title, detail) for one archived row; `row` is a dict or sqlite3.Row."""
    def g(key: str) -> object:
        return row[key]  # type: ignore[index]

    if kind == "meal":
        return str(g("title")), f"{g('slot')} on {g('day')}"
    if kind == "bill":
        return str(g("name")), f"{money_text(int(g('amount_cents')))} due {g('due_date')}"  # type: ignore[call-overload]
    if kind == "note":
        return str(g("title")), "Note"
    if kind == "expense":
        return str(g("description")), f"{money_text(int(g('amount_cents')))} on {g('day')}"  # type: ignore[call-overload]
    if kind == "template":
        return str(g("name")), f"{g('kind')} list"
    if kind == "event":
        return str(g("title")), str(g("day"))
    if kind == "goal":
        return str(g("name")), f"target {money_text(int(g('target_cents')))}"  # type: ignore[call-overload]
    return str(g("title")), "done" if g("done") else "to do"
