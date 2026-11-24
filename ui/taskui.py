"""Task card: checkbox, badges, subtask checklist and edit form (shared by pages)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import streamlit as st

from core.repo import Repository, Subtask, Task
from ui import theme
from ui.common import LABELS, RECURRENCES, archive_item, confirm_delete, load, run, set_undo

ASSIGNEES = ("either", "nick", "natalie")
PRIORITIES = ("high", "normal", "low")
ROTATE_LABEL = "Alternate between us each time"
SUBTASK_LIMIT_TASKS = 300


def load_subtasks(repo: Repository, tasks: list[Task]) -> dict[str, list[Subtask]]:
    """All subtasks for the shown tasks in one query, grouped by task id."""
    ids = [t.id for t in tasks][:SUBTASK_LIMIT_TASKS]
    grouped: dict[str, list[Subtask]] = defaultdict(list)
    if not ids:
        return grouped
    for sub in load(lambda: repo.list_subtasks(ids)):
        grouped[sub.task_id].append(sub)
    return grouped


def _toggle_task(repo: Repository, task: Task, key: str) -> None:
    if st.session_state.get(key):
        if run(repo.complete_task, task.id):
            set_undo("complete", task.id, task.title)
    else:
        run(repo.reopen_task, task.id)


def _toggle_sub(repo: Repository, sub: Subtask, key: str) -> None:
    run(repo.set_subtask_done, sub.id, bool(st.session_state.get(key)))


def _archive_sub(repo: Repository, sub_id: str, title: str = "step") -> None:
    archive_item("subtask", repo.archive_subtask, sub_id, title, "Step archived.")


def _delete_sub_ask(sub_id: str) -> None:
    st.session_state[f"subdel_{sub_id}"] = True


def _delete_sub(repo: Repository, sub_id: str) -> None:
    run(repo.delete_subtask, sub_id, ok="Step deleted.")


def _add_sub(repo: Repository, task_id: str) -> None:
    title = str(st.session_state.get(f"sn_{task_id}", "")).strip()
    if title:
        run(repo.add_subtask, task_id, title)


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


def widgets(prefix: str, task: Task | None) -> None:
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


def _do_save(repo: Repository, task_id: str) -> None:
    run(repo.update_task, task_id, ok="Task saved.", **_fields(f"te_{task_id}"))


def _archive(repo: Repository, task_id: str) -> None:
    if run(repo.archive_task, task_id, ok="Task archived."):
        set_undo("archive", task_id, "task")


def _edit_form(repo: Repository, task: Task) -> None:
    widgets(f"te_{task.id}", task)
    st.button("Save changes", type="primary", width="stretch", key=f"te_{task.id}_save",
              on_click=_do_save, args=(repo, task.id))
    with st.popover("Archive", icon=":material/inventory_2:", width="stretch"):
        st.write("Archive this task? It moves to Archived at the bottom of Tasks "
                 "and you can restore it any time.")
        st.button("Yes, archive", key=f"arch_{task.id}", on_click=_archive,
                  args=(repo, task.id), width="stretch")
    confirm_delete(f"task_{task.id}", repo.delete_task, task.id,
                   what="this task and its steps", ok="Task deleted.")


def _subtasks(repo: Repository, task: Task, subs: list[Subtask]) -> None:
    for sub in subs:
        key = f"sub_{sub.id}"
        with st.container(key=f"subrow_{sub.id}"):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.checkbox(sub.title, value=sub.done, key=key, on_change=_toggle_sub,
                          args=(repo, sub, key))
            with right.popover("", icon=":material/more_vert:", help="Step options"):
                st.button("Archive step", icon=":material/archive:", key=f"{key}_x",
                          on_click=_archive_sub, args=(repo, sub.id, sub.title), width="stretch")
                if st.session_state.get(f"subdel_{sub.id}"):
                    st.markdown("**Delete forever?**")
                    with st.container(key=f"del_sub_{sub.id}"):
                        st.button("Yes, delete forever", key=f"{key}_dy",
                                  on_click=_delete_sub, args=(repo, sub.id),
                                  width="stretch")
                else:
                    st.button("Delete step", icon=":material/delete:", key=f"{key}_d",
                              on_click=_delete_sub_ask, args=(sub.id,),
                              width="stretch")
    with st.form(f"sf_{task.id}", clear_on_submit=True, border=False):
        st.text_input("New step", key=f"sn_{task.id}", placeholder="Add a step",
                      label_visibility="collapsed")
        st.form_submit_button("Add step", icon=":material/add:", width="stretch",
                              on_click=_add_sub, args=(repo, task.id))


def task_card(
    repo: Repository,
    task: Task,
    prefix: str,
    today: date,
    subs: list[Subtask] | None = None,
    details: bool = True,
) -> None:
    """One task as a card. `details=False` gives the compact (Today page) version."""
    subs = subs or []
    with st.container(key=f"card_{prefix}_{task.id}"):
        key = f"{prefix}_chk_{task.id}"
        label = f"~~{task.title}~~" if task.status == "done" else task.title
        st.checkbox(label, value=task.status == "done", key=key, on_change=_toggle_task,
                    args=(repo, task, key))
        progress = ""
        if subs:
            progress = theme.badge(f"{sum(s.done for s in subs)}/{len(subs)} steps", "accent")
        repeat = theme.badge(f"Repeats {task.recurrence}", "neutral") \
            if task.recurrence != "none" else ""
        theme.pills(
            theme.person_badge(task.assignee),
            theme.due_badge(task.due_date, today) if task.status == "open" else "",
            theme.priority_badge(task.priority),
            repeat,
            progress,
        )
        if not details:
            return
        with st.expander("Steps, edit, delete", icon=":material/more_horiz:"):
            if task.notes:
                st.write(task.notes)
            _subtasks(repo, task, subs)
            st.divider()
            _edit_form(repo, task)
