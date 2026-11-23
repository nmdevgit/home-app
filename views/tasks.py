"""Tasks page: search, add, filters, complete/reopen, edit, archive."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import Repository, Task
from ui import state
from ui.common import LABELS, RECURRENCES, load, run, show_flash, task_checkbox
from ui.grouping import filter_tasks, search_tasks, sort_tasks

ASSIGNEES = ("either", "nick", "natalie")
PRIORITIES = ("high", "normal", "low")
ROTATE_LABEL = "Alternate between us each time"
LIMIT = 300


def _fields(prefix: str) -> dict[str, object]:
    """Read the add/edit widgets for `prefix` from session state."""
    get = st.session_state.get
    recurrence = get(f"{prefix}_rec", "none")
    due = get(f"{prefix}_due")
    return {
        "title": get(f"{prefix}_title", ""),
        "assignee": get(f"{prefix}_who", "either"),
        "due_date": due if isinstance(due, date) else None,
        "recurrence": recurrence,
        "notes": get(f"{prefix}_notes", ""),
        "priority": get(f"{prefix}_pri", "normal"),
        "rotate": bool(get(f"{prefix}_rot", False)) and recurrence != "none",
    }


def _widgets(prefix: str, task: Task | None) -> None:
    """Shared add/edit inputs. Not a form, so the rotate box can react to Repeats."""
    st.text_input("Title", value=task.title if task else "", key=f"{prefix}_title")
    who = task.assignee if task else "either"
    pri = task.priority if task else "normal"
    st.selectbox("Assignee", ASSIGNEES, index=ASSIGNEES.index(who),
                 format_func=LABELS.get, key=f"{prefix}_who")
    st.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(pri),
                 format_func=str.title, key=f"{prefix}_pri")
    st.date_input("Due date (optional)", value=task.due_date if task else None,
                  format="YYYY-MM-DD", key=f"{prefix}_due")
    rec = st.selectbox("Repeats", RECURRENCES,
                       index=RECURRENCES.index(task.recurrence if task else "none"),
                       key=f"{prefix}_rec")
    if rec != "none":
        st.checkbox(ROTATE_LABEL, value=task.rotate if task else False, key=f"{prefix}_rot")
    st.text_area("Notes", value=task.notes if task else "", key=f"{prefix}_notes")


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
    with st.expander("Add a task", expanded=False):
        _widgets("ta", None)
        st.button("Add task", type="primary", use_container_width=True,
                  on_click=_do_add, args=(repo,), key="ta_submit")


def _do_save(repo: Repository, task_id: str) -> None:
    f = _fields(f"te_{task_id}")
    run(repo.update_task, task_id, ok="Task saved.", **f)


def _archive(repo: Repository, task_id: str) -> None:
    run(repo.archive_task, task_id, ok="Task archived.")


def _edit_form(repo: Repository, task: Task) -> None:
    _widgets(f"te_{task.id}", task)
    st.button("Save", type="primary", use_container_width=True, key=f"te_{task.id}_save",
              on_click=_do_save, args=(repo, task.id))
    with st.popover("Archive", use_container_width=True):
        st.write("Archive this task? It is hidden from lists but kept.")
        st.button("Yes, archive", key=f"arch_{task.id}", on_click=_archive,
                  args=(repo, task.id), use_container_width=True)


def _task_item(repo: Repository, task: Task) -> None:
    task_checkbox(repo, task, "tasks")
    meta = f"For {LABELS[task.assignee]}"
    if task.rotate:
        meta += ", alternating"
    with st.expander(f"Details - {meta}"):
        if task.notes:
            st.write(task.notes)
        _edit_form(repo, task)


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Tasks")
    show_flash()
    _add_form(repo)
    query = st.text_input("Search", key="t_search", placeholder="Search title or notes",
                          label_visibility="collapsed")
    scope = st.segmented_control("Show", ["Mine", "All"], default="All", key="t_scope")
    status = st.segmented_control("Status", ["Open", "Done"], default="Open", key="t_status")
    tasks: list[Task] = load(lambda: repo.list_tasks(include_done=True, limit=LIMIT))
    shown = filter_tasks(tasks, me, scope != "All", status == "Done")
    shown = sort_tasks(search_tasks(shown, query))
    if not shown:
        st.info("No tasks here.")
    for task in shown:
        _task_item(repo, task)
