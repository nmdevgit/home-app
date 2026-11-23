"""Tasks page: add form, filters, complete/reopen, edit, archive."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import Repository, Task
from ui import state
from ui.common import LABELS, RECURRENCES, load, run, show_flash, task_checkbox
from ui.grouping import filter_tasks

ASSIGNEES = ("either", "nick", "natalie")


def _add_form(repo: Repository, me: str) -> None:
    with st.expander("Add a task", expanded=False):
        with st.form("task_add", clear_on_submit=True, border=False):
            title = st.text_input("Title")
            assignee = st.selectbox("Assignee", ASSIGNEES, index=ASSIGNEES.index("either"),
                                    format_func=LABELS.get)
            due = st.date_input("Due date (optional)", value=None, format="YYYY-MM-DD")
            recurrence = st.selectbox("Repeats", RECURRENCES)
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Add task", type="primary", use_container_width=True)
        if submitted:
            if run(repo.add_task, title, assignee, due, recurrence, notes, ok="Task added."):
                st.rerun()
            show_flash()


def _archive(repo: Repository, task_id: str) -> None:
    run(repo.archive_task, task_id, ok="Task archived.")


def _edit_form(repo: Repository, task: Task) -> None:
    with st.form(f"edit_{task.id}", border=False):
        title = st.text_input("Title", value=task.title)
        assignee = st.selectbox("Assignee", ASSIGNEES, index=ASSIGNEES.index(task.assignee),
                                format_func=LABELS.get)
        due = st.date_input("Due date (optional)", value=task.due_date, format="YYYY-MM-DD")
        recurrence = st.selectbox("Repeats", RECURRENCES, index=RECURRENCES.index(task.recurrence))
        notes = st.text_area("Notes", value=task.notes)
        saved = st.form_submit_button("Save", type="primary", use_container_width=True)
    if saved and run(repo.update_task, task.id, title=title, assignee=assignee,
                     due_date=due if isinstance(due, date) else None,
                     recurrence=recurrence, notes=notes, ok="Task saved."):
        st.rerun()
    with st.popover("Archive", use_container_width=True):
        st.write("Archive this task? It is hidden from lists but kept.")
        st.button("Yes, archive", key=f"arch_{task.id}", on_click=_archive,
                  args=(repo, task.id), use_container_width=True)


def _task_item(repo: Repository, task: Task) -> None:
    task_checkbox(repo, task, "tasks")
    meta = f"For {LABELS[task.assignee]}"
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
    _add_form(repo, me)
    scope = st.segmented_control("Show", ["Mine", "All"], default="Mine", key="t_scope")
    status = st.segmented_control("Status", ["Open", "Done"], default="Open", key="t_status")
    tasks: list[Task] = load(lambda: repo.list_tasks(include_done=True))
    shown = filter_tasks(tasks, me, scope != "All", status == "Done")
    if not shown:
        st.info("No tasks here.")
    for task in shown:
        _task_item(repo, task)
