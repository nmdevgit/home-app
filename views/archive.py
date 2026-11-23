"""Archive page: restore archived tasks/grocery, and 'Done this week' history."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from core.repo import GroceryItem, Repository, Task
from ui import state
from ui.common import LABELS, clock, load, now_local, run, show_flash

LIMIT = 200


def _restore_task(repo: Repository, task_id: str) -> None:
    run(repo.restore_task, task_id, ok="Task restored.")


def _restore_item(repo: Repository, item_id: str) -> None:
    run(repo.restore_grocery, item_id, ok="Item restored.")


def _tasks_tab(repo: Repository) -> None:
    tasks: list[Task] = load(lambda: repo.list_archived_tasks(limit=LIMIT))
    if not tasks:
        st.info("No archived tasks.")
    for task in tasks:
        st.write(f"**{task.title}** - for {LABELS[task.assignee]}")
        st.button("Restore", key=f"rt_{task.id}", on_click=_restore_task,
                  args=(repo, task.id), use_container_width=True)


def _grocery_tab(repo: Repository) -> None:
    items: list[GroceryItem] = load(lambda: repo.list_archived_grocery(limit=LIMIT))
    if not items:
        st.info("No archived grocery items.")
    for item in items:
        label = f"{item.name} ({item.quantity})" if item.quantity else item.name
        st.write(f"**{label}**")
        st.button("Restore", key=f"rg_{item.id}", on_click=_restore_item,
                  args=(repo, item.id), use_container_width=True)


def _done_tab(repo: Repository) -> None:
    since = now_local() - timedelta(days=7)
    zone = clock.get_zone(state.secret("APP_TZ") or None)
    done: list[Task] = load(lambda: repo.list_done_tasks(since, limit=LIMIT))
    if not done:
        st.info("Nothing completed in the last 7 days.")
    for task in done:
        when = task.completed_at.astimezone(zone) if task.completed_at else None
        stamp = f"{when:%a %d %b, %H:%M}" if when else "unknown time"
        st.write(f"{task.title} - {stamp} (task for {LABELS[task.assignee]})")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Archive")
    show_flash()
    done_tab, tasks_tab, grocery_tab = st.tabs(["Done this week", "Tasks", "Grocery"])
    with done_tab:
        _done_tab(repo)
    with tasks_tab:
        _tasks_tab(repo)
    with grocery_tab:
        _grocery_tab(repo)
