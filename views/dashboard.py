"""Today dashboard: overdue, due today, next 7 days, grouped by owner."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core.repo import Bill, Meal, Repository, Task
from ui import state
from ui.common import load, show_flash, task_checkbox, today
from ui.grouping import bill_status, bucket_of, group_by_owner, partner_of
from ui.money import format_cents

SECTIONS = (("overdue", "Overdue"), ("today", "Due today"), ("upcoming", "Next 7 days"))


def _render_bucket(repo: Repository, tasks: list[Task], me: str, name: str) -> None:
    groups = group_by_owner(tasks, me)
    titles = {"mine": "Mine", "partner": partner_of(me).title(), "either": "Either of us"}
    for group, items in groups.items():
        if not items:
            continue
        st.caption(titles[group])
        for task in items:
            task_checkbox(repo, task, f"dash_{name}")


def _bills_card(repo: Repository, now: date) -> None:
    bills: list[Bill] = load(lambda: repo.list_bills(limit=200))
    horizon = now + timedelta(days=7)
    due = [b for b in bills if b.due_date <= horizon
           and bill_status(b.due_date, now, b.last_paid_on) != "paid"]
    if not due:
        return
    st.subheader("Bills due in next 7 days")
    for bill in sorted(due, key=lambda b: b.due_date):
        flag = " :red[overdue]" if bill.due_date < now else ""
        st.write(f"{bill.name} - {format_cents(bill.amount_cents)} - "
                 f"{bill.due_date:%a %d %b}{flag}")


def _meals_card(repo: Repository, now: date) -> None:
    meals: list[Meal] = load(lambda: repo.list_meals(now, now, limit=20))
    if not meals:
        return
    st.subheader("Today's meals")
    for meal in meals:
        st.write(f"{meal.slot.title()}: {meal.title}")


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Today")
    show_flash()
    now = today()
    _meals_card(repo, now)
    _bills_card(repo, now)
    open_tasks: list[Task] = load(lambda: repo.list_tasks(include_done=False, limit=300))
    buckets: dict[str, list[Task]] = {key: [] for key, _ in SECTIONS}
    for task in open_tasks:
        bucket = bucket_of(task, now)
        if bucket:
            buckets[bucket].append(task)
    if not any(buckets.values()):
        st.success("Nothing due in the next 7 days.")
        return
    for key, title in SECTIONS:
        if buckets[key]:
            st.subheader(f"{title} ({len(buckets[key])})")
            _render_bucket(repo, buckets[key], me, key)
