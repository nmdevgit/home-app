"""Today page: greeting + progress, overdue, due today, bills, dinner, needs attention."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import clock
from core.repo import Bill, Meal, Repository, Task
from ui import state, theme
from ui.common import load, now_local, show_flash, today
from ui.grouping import bill_status, bucket_of
from ui.money import format_cents
from ui.taskui import load_subtasks, task_card

ATTENTION_MAX = 5


def greeting(hour: int, name: str) -> str:
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {part}, {name}"


def done_today_count(done: list[Task], now: date) -> int:
    zone = clock.get_zone(state.secret("APP_TZ") or None)
    count = 0
    for task in done:
        if task.completed_at and task.completed_at.astimezone(zone).date() == now:
            count += 1
    return count


def _split(open_tasks: list[Task], now: date) -> tuple[list[Task], list[Task], list[Task]]:
    overdue, due_today, attention = [], [], []
    for task in open_tasks:
        bucket = bucket_of(task, now)
        if bucket == "overdue":
            overdue.append(task)
        elif bucket == "today":
            due_today.append(task)
        elif task.priority == "high":
            attention.append(task)
    return overdue, due_today, attention[:ATTENTION_MAX]


def _task_cards(repo: Repository, tasks: list[Task], prefix: str, now: date) -> None:
    subs = load_subtasks(repo, tasks)
    for task in sorted(tasks, key=lambda t: (t.due_date or date.max, t.title.lower())):
        task_card(repo, task, prefix, now, subs.get(task.id, []), details=False)


def _bills_card(repo: Repository, now: date) -> None:
    bills: list[Bill] = load(lambda: repo.list_bills(limit=200))
    horizon = now + timedelta(days=7)
    due = [b for b in bills if b.due_date <= horizon
           and bill_status(b.due_date, now, b.last_paid_on) != "paid"]
    if not due:
        return
    theme.section("Bills due", len(due))
    with st.container(key="card_dash_bills"):
        for bill in sorted(due, key=lambda b: b.due_date):
            st.write(f"**{bill.name}**  {format_cents(bill.amount_cents)}")
            theme.pills(theme.due_badge(bill.due_date, now))


def _dinner_card(repo: Repository, now: date) -> None:
    meals: list[Meal] = load(lambda: repo.list_meals(now, now, limit=20))
    dinners = [m for m in meals if m.slot == "dinner"]
    theme.section("Tonight's dinner")
    with st.container(key="card_dash_dinner"):
        if not dinners:
            st.caption("Nothing planned yet. Add one on the Meals page.")
        for meal in dinners:
            st.write(f"**{meal.title}**")


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    now, clock_now = today(), now_local()
    show_flash()
    open_tasks: list[Task] = load(lambda: repo.list_tasks(include_done=False, limit=300))
    start = datetime.combine(now, datetime.min.time(), tzinfo=clock_now.tzinfo)
    done = load(lambda: repo.list_done_tasks(start, limit=200))
    overdue, due_today, attention = _split(open_tasks, now)
    finished = done_today_count(done, now)
    total = finished + len(overdue) + len(due_today)
    theme.hero(greeting(clock_now.hour, me.title()), f"{now:%A %d %B %Y}", finished, total)
    if overdue:
        theme.section("Overdue", len(overdue), "bad")
        _task_cards(repo, overdue, "dash_over", now)
    theme.section("Due today", len(due_today))
    if due_today:
        _task_cards(repo, due_today, "dash_today", now)
    else:
        theme.empty("Nothing due today", "Enjoy it, or pick something from Tasks.")
    _bills_card(repo, now)
    _dinner_card(repo, now)
    if attention:
        theme.section("Needs attention", len(attention))
        _task_cards(repo, attention, "dash_attn", now)
