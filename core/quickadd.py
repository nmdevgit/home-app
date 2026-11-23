"""Local rule-based quick-add parsers (no AI, no network). Both are total functions:
odd input never raises; the worst case is the cleaned text returned as the title/name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from core import rules
from core.repo import Assignee, GroceryCategory, Priority, Recurrence

_WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}  # fmt: skip
_FLAGS = re.IGNORECASE

_PRIORITY_RE = re.compile(r"(?<!\S)!(high|urgent|low|normal)\b", _FLAGS)
_ASSIGNEE_RE = re.compile(r"\bfor\s+(nick|natalie)\b", _FLAGS)
_RECUR_RE = re.compile(r"\bevery\s+(day|week|month)\b", _FLAGS)
_RELATIVE_RE = re.compile(r"\b(today|tomorrow|next\s+week|next\s+month)\b", _FLAGS)
_IN_RE = re.compile(r"\bin\s+(\d{1,3})\s+(day|week)s?\b", _FLAGS)
_WEEKDAY_RE = re.compile(
    r"\b(?:(?:on|next)\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b",
    _FLAGS,
)
_NUMERIC_DATE_RE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")

_PRIORITY_MAP: dict[str, Priority] = {
    "high": "high", "urgent": "high", "low": "low", "normal": "normal",
}  # fmt: skip
_RECUR_MAP: dict[str, Recurrence] = {"day": "daily", "week": "weekly", "month": "monthly"}


@dataclass(frozen=True)
class QuickTask:
    title: str
    assignee: Assignee = "either"
    due_date: date | None = None
    priority: Priority = "normal"
    recurrence: Recurrence = "none"


@dataclass(frozen=True)
class QuickGrocery:
    name: str
    quantity: str = ""
    category: GroceryCategory = "other"


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" ,;:-")


def _cut(text: str, match: re.Match[str]) -> str:
    return text[: match.start()] + " " + text[match.end() :]


def _next_weekday(today: date, weekday: int) -> date:
    """Soonest matching weekday strictly after today (so 'mon' on a Monday is +7)."""
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _numeric_date(match: re.Match[str], today: date) -> date | None:
    day, month, year_text = int(match.group(1)), int(match.group(2)), match.group(3)
    if year_text:
        year = int(year_text)
        years = [year + 2000 if year < 100 else year]
    else:  # this year, else the next year it exists in (29/02 skips to a leap year)
        years = [today.year + k for k in range(5)]
    for year in years:
        try:
            candidate = date(year, month, day)
        except ValueError:  # 31/02, 0/5, year out of range...
            continue
        if year_text or candidate >= today:
            return candidate
    return None


def _extract_date(text: str, today: date) -> tuple[str, date | None]:
    match = _IN_RE.search(text)
    if match:
        step = 7 if match.group(2).lower() == "week" else 1
        try:
            return _cut(text, match), today + timedelta(days=int(match.group(1)) * step)
        except OverflowError:
            return text, None
    match = _RELATIVE_RE.search(text)
    if match:
        word = " ".join(match.group(1).lower().split())
        if word == "today":
            due = today
        elif word == "tomorrow":
            due = today + timedelta(days=1)
        elif word == "next week":
            due = today + timedelta(days=7)
        else:
            due = rules.add_months(today, 1)
        return _cut(text, match), due
    match = _WEEKDAY_RE.search(text)
    if match:
        return _cut(text, match), _next_weekday(today, _WEEKDAYS[match.group(1).lower()])
    for match in _NUMERIC_DATE_RE.finditer(text):
        due = _numeric_date(match, today)
        if due is not None:
            return _cut(text, match), due
    return text, None


def parse_quick_task(text: str, today: date) -> QuickTask:
    """Parse e.g. 'bins tomorrow for natalie !high every week'.

    Understood (case-insensitive, first match of each kind is used and removed):
      priority    !high / !urgent -> high, !low -> low, !normal
      assignee    'for nick' / 'for natalie'
      recurrence  'every day|week|month'
      due date    today, tomorrow, next week, next month, in N days/weeks, a weekday
                  (mon..sun, 'on fri', 'next fri': the soonest one strictly after today),
                  dd/mm or dd/mm/yy(yy) (no year: this year, or next if already past)
    Never raises; if nothing is left as a title the cleaned input is used.
    """
    raw = text if isinstance(text, str) else ""
    rest = raw
    priority: Priority = "normal"
    assignee: Assignee = "either"
    recurrence: Recurrence = "none"
    due: date | None = None
    if match := _PRIORITY_RE.search(rest):
        priority = _PRIORITY_MAP[match.group(1).lower()]
        rest = _cut(rest, match)
    if match := _ASSIGNEE_RE.search(rest):
        assignee = "nick" if match.group(1).lower() == "nick" else "natalie"
        rest = _cut(rest, match)
    if match := _RECUR_RE.search(rest):
        recurrence = _RECUR_MAP[match.group(1).lower()]
        rest = _cut(rest, match)
    if isinstance(today, date):
        rest, due = _extract_date(rest, today)
    title = _tidy(rest) or _tidy(raw)
    return QuickTask(
        title=title[: rules.MAX_TITLE],
        assignee=assignee,
        due_date=due,
        priority=priority,
        recurrence=recurrence,
    )


# ---- grocery ---------------------------------------------------------------
_UNITS = (
    "kg|g|l|ml|lb|lbs|oz|pack|packs|dozen|bottle|bottles|can|cans|bag|bags|loaf|loaves|box|boxes"
)
_NUM = r"\d+(?:[.,]\d+)?"
_LEAD_X_RE = re.compile(rf"^({_NUM})\s*x\s*(.+)$", _FLAGS)
_LEAD_UNIT_RE = re.compile(rf"^({_NUM})\s*({_UNITS})\b\s*(?:of\s+)?(.+)$", _FLAGS)
_LEAD_NUM_RE = re.compile(rf"^({_NUM})\s+(.+)$")
_TRAIL_X_RE = re.compile(rf"^(.+?)\s+x\s*({_NUM})$", _FLAGS)
_TRAIL_UNIT_RE = re.compile(rf"^(.+?)\s+({_NUM})\s*({_UNITS})$", _FLAGS)
_TRAIL_NUM_RE = re.compile(rf"^(.+?)\s+({_NUM})$")

_PHRASES: dict[str, GroceryCategory] = {
    "ice cream": "frozen", "frozen veg": "frozen", "peanut butter": "pantry",
    "cream cheese": "dairy", "sour cream": "dairy", "toilet paper": "household",
    "washing powder": "household", "washing liquid": "household", "bin bags": "household",
    "dish soap": "household", "orange juice": "drinks", "apple juice": "drinks",
    "sparkling water": "drinks", "olive oil": "pantry", "baking powder": "pantry",
}  # fmt: skip
_KEYWORDS: dict[GroceryCategory, tuple[str, ...]] = {
    "produce": (
        "apple banana orange lemon lime pear grape berry strawberry blueberry avocado tomato "
        "potato onion garlic carrot broccoli spinach lettuce cucumber capsicum pepper mushroom "
        "zucchini celery pumpkin corn salad fruit veg vegetable herb basil ginger mango "
        "melon cabbage cauliflower kale"
    ).split(),
    "dairy": "milk cheese butter yoghurt yogurt cream egg margarine".split(),
    "meat": (
        "chicken beef pork lamb mince steak sausage bacon ham salmon fish prawn tuna turkey "
        "meat"
    ).split(),
    "bakery": "bread loaf roll bun bagel croissant muffin cake wrap tortilla pita".split(),
    "pantry": (
        "rice pasta flour sugar salt oil sauce cereal oat oats tin can bean lentil noodle "
        "spice stock honey jam vinegar biscuit cracker chip snack nut coffee tea"
    ).split(),
    "frozen": "frozen pizza".split(),
    "drinks": "water juice soda cola beer wine drink lemonade kombucha".split(),
    "household": (
        "soap shampoo toothpaste detergent bleach sponge tissue towel foil cling nappy "
        "deodorant cleaner dishwasher"
    ).split(),
}


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def guess_category(name: str) -> GroceryCategory:
    """Keyword -> category guess; 'other' when nothing matches."""
    lowered = " ".join(name.lower().split())
    for phrase, category in _PHRASES.items():
        if phrase in lowered:
            return category
    words = [_singular(w) for w in re.findall(r"[a-z]+", lowered)]
    for category, keywords in _KEYWORDS.items():
        if any(w in keywords for w in words):
            return category
    return "other"


def _split_quantity(text: str) -> tuple[str, str]:
    """Return (name, quantity) for '2 x milk', 'milk 2L', '2kg apples', 'milk x2', '3 eggs'."""
    if m := _LEAD_X_RE.match(text):
        return m.group(2), m.group(1)
    if m := _LEAD_UNIT_RE.match(text):
        return m.group(3), f"{m.group(1)}{m.group(2).lower()}"
    if m := _LEAD_NUM_RE.match(text):
        return m.group(2), m.group(1)
    if m := _TRAIL_X_RE.match(text):
        return m.group(1), m.group(2)
    if m := _TRAIL_UNIT_RE.match(text):
        return m.group(1), f"{m.group(2)}{m.group(3).lower()}"
    if m := _TRAIL_NUM_RE.match(text):
        return m.group(1), m.group(2)
    return text, ""


def parse_quick_grocery(text: str) -> QuickGrocery:
    """Parse '2 x milk', 'milk 2L', '3 eggs' into name/quantity/category. Never raises."""
    raw = _tidy(text) if isinstance(text, str) else ""
    name, quantity = _split_quantity(raw)
    name = _tidy(name) or raw  # a bare number like '5' stays as the name
    name = name[: rules.MAX_GROCERY_NAME]
    return QuickGrocery(
        name=name, quantity=quantity[: rules.MAX_QUANTITY], category=guess_category(name)
    )
