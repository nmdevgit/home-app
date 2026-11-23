"""Tasks page: quick add with preview, schedule groups, subtasks, edit, archive."""
from __future__ import annotations

import streamlit as st

from core.errors import RepositoryError
from core.quickadd import QuickTask, parse_quick_task
from core.repo import Repository, Task
from ui import state, theme
from ui.common import load, run, show_flash, today
from ui.grouping import SCHEDULE_ORDER, filter_tasks, group_schedule, search_tasks, sort_tasks
from ui.taskui import _fields, load_subtasks, task_card, widgets

LIMIT = 300
PENDING = "tq_pending"


def _preview(repo: Repository) -> None:
    """Parse the quick-add text and hold the result until the user confirms."""
    text = str(st.session_state.get("tq_text", "")).strip()
    if not text:
        return
    try:
        st.session_state[PENDING] = parse_quick_task(text, today())
    except (RepositoryError, ValueError) as exc:
        st.session_state.pop(PENDING, None)
        st.session_state["_flash"] = [("error", f"Could not read that: {exc}")]


def _confirm(repo: Repository) -> None:
    quick: QuickTask | None = st.session_state.get(PENDING)
    if quick is None:
        return
    ok = run(repo.add_task, quick.title, quick.assignee, quick.due_date, quick.recurrence,
             "", quick.priority, False, ok="Task added.")
    if ok:
        st.session_state.pop(PENDING, None)
        st.session_state["tq_text"] = ""


def _cancel() -> None:
    st.session_state.pop(PENDING, None)


def _quick_add(repo: Repository) -> None:
    with st.form("tq_form", border=False):
        st.text_input("Quick add", key="tq_text", label_visibility="collapsed",
                      placeholder="Try: vacuum friday for natalie !high every week")
        st.form_submit_button("Preview", icon=":material/bolt:", use_container_width=True,
                              on_click=_preview, args=(repo,))
    quick: QuickTask | None = st.session_state.get(PENDING)
    if quick is None:
        return
    with st.container(key="card_quick_preview"):
        st.caption("Here is what I understood")
        st.write(f"**{quick.title}**")
        repeat = theme.badge(f"Repeats {quick.recurrence}") if quick.recurrence != "none" else ""
        theme.pills(
            theme.person_badge(quick.assignee),
            theme.due_badge(quick.due_date, today()) if quick.due_date else theme.badge("No date"),
            theme.priority_badge(quick.priority),
            repeat,
        )
        left, right = st.columns(2)
        left.button("Add task", type="primary", icon=":material/check:", key="tq_ok",
                    on_click=_confirm, args=(repo,), use_container_width=True)
        right.button("Cancel", key="tq_cancel", on_click=_cancel, use_container_width=True)


def _do_add(repo: Repository) -> None:
    f = _fields("ta")
    ok = run(repo.add_task, f["title"], f["assignee"], f["due_date"], f["recurrence"],
             f["notes"], f["priority"], f["rotate"], ok="Task added.")
    if ok:
        for suffix in ("title", "notes", "due"):
            st.session_state.pop(f"ta_{suffix}", None)
        st.session_state["ta_rec"] = "none"
        st.session_state["ta_rot"] = False


def _add_form(repo: Repository) -> None:
    with st.expander("Add with all the details"):
        widgets("ta", None)
        st.button("Add task", type="primary", use_container_width=True,
                  on_click=_do_add, args=(repo,), key="ta_submit")


def _render_groups(repo: Repository, shown: list[Task], status: str | None) -> None:
    now = today()
    subs = load_subtasks(repo, shown)
    if status == "Done":
        theme.section("Done", len(shown))
        for task in shown:
            task_card(repo, task, "tasks", now, subs.get(task.id, []))
        return
    titles = dict(SCHEDULE_ORDER)
    for key, items in group_schedule(shown, now).items():
        theme.section(titles[key], len(items), "bad" if key == "overdue" else "")
        for task in items:
            task_card(repo, task, "tasks", now, subs.get(task.id, []))


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Tasks")
    show_flash()
    _quick_add(repo)
    _add_form(repo)
    query = st.text_input("Search", key="t_search", placeholder="Search title or notes",
                          label_visibility="collapsed")
    scope = st.segmented_control("Show", ["Mine", "All"], default="All", key="t_scope")
    status = st.segmented_control("Status", ["Open", "Done"], default="Open", key="t_status")
    tasks: list[Task] = load(lambda: repo.list_tasks(include_done=True, limit=LIMIT))
    shown = filter_tasks(tasks, me, scope != "All", status == "Done")
    shown = sort_tasks(search_tasks(shown, query))
    if not shown:
        theme.empty("Nothing here", "Add one with quick add above.")
        return
    _render_groups(repo, shown, status)
