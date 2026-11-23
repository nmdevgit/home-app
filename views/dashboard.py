"""Today dashboard: overdue, due today, next 7 days, grouped by owner."""
from __future__ import annotations

import streamlit as st

from core.repo import Repository, Task
from ui import state
from ui.common import load, show_flash, task_checkbox, today
from ui.grouping import bucket_of, group_by_owner, partner_of

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


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Today")
    show_flash()
    now = today()
    open_tasks: list[Task] = load(lambda: repo.list_tasks(include_done=False))
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
