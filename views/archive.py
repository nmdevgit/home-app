"""Archive - nothing is lost: restore anything, anytime; 'Done this week' history."""
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import streamlit as st

from core.repo import ArchivedItem, GroceryItem, Repository, Task
from ui import state, theme
from ui.common import clock, confirm_delete, load, now_local, run, show_flash

LIMIT = 200


def _restore_task(repo: Repository, task_id: str) -> None:
    run(repo.restore_task, task_id, ok="Task restored.")


def _restore_item(repo: Repository, item_id: str) -> None:
    run(repo.restore_grocery, item_id, ok="Item restored.")


def _tasks_tab(repo: Repository) -> None:
    tasks: list[Task] = load(lambda: repo.list_archived_tasks(limit=LIMIT))
    if not tasks:
        theme.empty("No archived tasks", "Archived tasks wait here until you restore them.")
    for task in tasks:
        with st.container(key=f"card_arch_t_{task.id}"):
            st.write(f"**{task.title}**")
            theme.pills(theme.person_badge(task.assignee))
            st.button("Restore", key=f"rt_{task.id}", icon=":material/restore:",
                      on_click=_restore_task, args=(repo, task.id), width="stretch")
            confirm_delete(f"at_{task.id}", repo.delete_task, task.id, what="this task",
                           ok="Task deleted.")


def _grocery_tab(repo: Repository) -> None:
    items: list[GroceryItem] = load(lambda: repo.list_archived_grocery(limit=LIMIT))
    if not items:
        theme.empty("No archived grocery items")
    for item in items:
        label = f"{item.name} ({item.quantity})" if item.quantity else item.name
        with st.container(key=f"card_arch_g_{item.id}"):
            st.write(f"**{label}**")
            st.button("Restore", key=f"rg_{item.id}", icon=":material/restore:",
                      on_click=_restore_item, args=(repo, item.id), width="stretch")
            confirm_delete(f"ag_{item.id}", repo.delete_grocery, item.id, what=item.name,
                           ok="Item deleted.")


_KINDS = {"meal": "Meal", "bill": "Bill", "note": "Note", "expense": "Expense",
          "template": "Template", "event": "Event", "goal": "Goal", "subtask": "Step"}


def _restore_any(repo: Repository, kind: str, item_id: str) -> None:
    run(repo.restore_item, kind, item_id, ok="Restored.")


def _delete_fn(repo: Repository, kind: str) -> Callable[[str], None]:
    return {"meal": repo.delete_meal, "bill": repo.delete_bill, "note": repo.delete_note,
            "expense": repo.delete_expense, "template": repo.delete_template,
            "event": repo.delete_event, "goal": repo.delete_goal,
            "subtask": repo.delete_subtask}[kind]


def _other_tab(repo: Repository) -> None:
    items: list[ArchivedItem] = load(lambda: repo.list_archived_items(limit=LIMIT))
    if not items:
        theme.empty("Nothing else archived", "Archived meals, bills, notes and more wait here.")
    for item in items:
        with st.container(key=f"card_arch_o_{item.kind}_{item.id}"):
            st.write(f"**{item.title}**")
            theme.pills(theme.badge(_KINDS.get(item.kind, item.kind), "accent"),
                        theme.badge(item.detail) if item.detail else "")
            st.button("Restore", key=f"ro_{item.kind}_{item.id}", icon=":material/restore:",
                      on_click=_restore_any, args=(repo, item.kind, item.id), width="stretch")
            confirm_delete(f"ao_{item.kind}_{item.id}", _delete_fn(repo, item.kind), item.id,
                           what=item.title, ok="Deleted.")


def _done_tab(repo: Repository) -> None:
    since = now_local() - timedelta(days=7)
    zone = clock.get_zone(state.secret("APP_TZ") or None)
    done: list[Task] = load(lambda: repo.list_done_tasks(since, limit=LIMIT))
    if not done:
        theme.empty("Nothing completed yet", "Finished tasks from the last 7 days show up here.")
    for task in done:
        when = task.completed_at.astimezone(zone) if task.completed_at else None
        stamp = f"{when:%a %d %b, %H:%M}" if when else "unknown time"
        with st.container(key=f"card_done_{task.id}"):
            st.write(f"**{task.title}**")
            theme.pills(theme.person_badge(task.assignee), theme.badge(stamp))


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Archive")
    st.caption("Nothing is lost - restore anything, anytime.")
    show_flash()
    confirm_delete("purge", repo.purge_archived, what="everything in the archive",
                   ok="Archive emptied.", label="Delete everything archived")
    done_tab, tasks_tab, grocery_tab, other_tab = st.tabs(
        ["Done this week", "Tasks", "Grocery", "Everything else"])
    with done_tab:
        _done_tab(repo)
    with tasks_tab:
        _tasks_tab(repo)
    with grocery_tab:
        _grocery_tab(repo)
    with other_tab:
        _other_tab(repo)
