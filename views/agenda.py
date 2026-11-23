"""Agenda: a week at a glance (tasks due, bills due, meals), read-only."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core.repo import Bill, Meal, Task
from ui import state, theme
from ui.common import load, show_flash, today
from ui.grouping import bill_status, week_start
from ui.money import format_cents

KEY = "ag_week"


def _shift(days: int) -> None:
    st.session_state[KEY] = st.session_state[KEY] + timedelta(days=days)


def _this_week() -> None:
    st.session_state[KEY] = week_start(today())


def day_entries(
    day: date, tasks: list[Task], bills: list[Bill], meals: list[Meal], now: date
) -> list[tuple[str, str]]:
    """(kind, text) entries for one day; kind is task / bill / meal."""
    out: list[tuple[str, str]] = []
    out += [("meal", f"{m.slot.title()}: {m.title}") for m in meals if m.day == day]
    out += [("task", t.title) for t in tasks if t.due_date == day]
    unpaid = [b for b in bills if bill_status(b.due_date, now, b.last_paid_on) != "paid"]
    out += [("bill", f"{b.name} {format_cents(b.amount_cents)}")
            for b in unpaid if b.due_date == day]
    return out


def _task_assignees(tasks: list[Task], day: date) -> str:
    people = {t.assignee for t in tasks if t.due_date == day}
    return "".join(theme.avatar(p) for p in sorted(people))


def _day_card(day: date, entries: list[tuple[str, str]], now: date, tasks: list[Task]) -> None:
    label = f"{day:%A %d %b}"
    tone = "accent" if day == now else "neutral"
    with st.container(key=f"card_agenda_{day.isoformat()}"):
        theme.pills(theme.badge(label, tone), theme.badge("Today") if day == now else "",
                    _task_assignees(tasks, day))
        if not entries:
            st.caption("Nothing on.")
        icons = {"task": ":material/checklist:", "bill": ":material/receipt_long:",
                 "meal": ":material/restaurant:"}
        for kind, text in entries:
            st.markdown(f"{icons[kind]} {text}")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Agenda")
    show_flash()
    now = today()
    st.session_state.setdefault(KEY, week_start(now))
    start: date = st.session_state[KEY]
    end = start + timedelta(days=6)
    prev_col, mid_col, next_col = st.columns(3)
    prev_col.button("Prev", icon=":material/chevron_left:", on_click=_shift, args=(-7,),
                    use_container_width=True, key="ag_prev")
    mid_col.button("This week", on_click=_this_week, use_container_width=True, key="ag_now")
    next_col.button("Next", icon=":material/chevron_right:", on_click=_shift, args=(7,),
                    use_container_width=True, key="ag_next")
    st.caption(theme.week_label(start))
    tasks: list[Task] = [t for t in load(lambda: repo.list_tasks(include_done=False, limit=300))
                         if t.due_date and start <= t.due_date <= end]
    bills: list[Bill] = load(lambda: repo.list_bills(limit=200))
    meals: list[Meal] = load(lambda: repo.list_meals(start, end, limit=100))
    for offset in range(7):
        day = start + timedelta(days=offset)
        _day_card(day, day_entries(day, tasks, bills, meals, now), now, tasks)
