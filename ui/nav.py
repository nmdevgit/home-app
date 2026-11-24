"""Single source of truth for navigation url_paths, so signed-in and signed-out navs can't drift."""
from __future__ import annotations

from collections.abc import Callable

# (group, title, icon, url_path, module name in views/). First entry is the default page.
PAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("", "Today", ":material/today:", "today", "dashboard"),
    ("", "Tasks", ":material/checklist:", "tasks", "tasks"),
    ("", "Grocery", ":material/shopping_cart:", "grocery", "grocery"),
    ("Plan", "Agenda", ":material/calendar_month:", "agenda", "agenda"),
    ("Plan", "Meals", ":material/restaurant:", "meals", "meals"),
    ("Plan", "Bills", ":material/receipt_long:", "bills", "bills"),
    ("Plan", "Expenses", ":material/payments:", "expenses", "expenses"),
    ("More", "Templates", ":material/library_add_check:", "templates", "templates"),
    ("More", "Notes", ":material/sticky_note_2:", "notes", "notes"),
    ("More", "More", ":material/menu:", "more", "more"),
    ("More", "Calendar", ":material/event:", "calendar", "events"),
    ("More", "Goals", ":material/savings:", "goals", "goals"),
    ("More", "Search", ":material/search:", "search", "search"),
    ("More", "Activity", ":material/history:", "activity", "activity"),
    ("More", "Stats", ":material/bar_chart:", "stats", "stats"),
    ("More", "Archive", ":material/inventory_2:", "archive", "archive"),
    ("More", "Settings", ":material/settings:", "settings", "settings"),
)


PAGES_KEY = "_nav_pages"


def url_paths() -> list[str]:
    return [p[3] for p in PAGES]


def login_stub(render: Callable[[], None], url_path: str) -> Callable[[], None]:
    """A distinct function object per path (Streamlit hashes callables; duplicates collide)."""
    def page() -> None:
        render()
    page.__name__ = f"login_{url_path}"
    page.__qualname__ = page.__name__
    return page


# Bottom tab bar entries (url_path); everything else is reached from the More hub.
TABS: tuple[str, ...] = ("today", "tasks", "grocery", "more")  # + quick-add button in the middle


def more_links() -> list[tuple[str, str, str]]:
    return [(p[3], p[1], p[2]) for p in PAGES if p[3] not in TABS]
