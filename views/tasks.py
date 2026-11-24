"""Tasks page: quick add with preview, schedule groups, subtasks, edit, archive."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import streamlit as st

from core.errors import RepositoryError
from core.quickadd import QuickTask, parse_quick_task
from core.repo import Repository, Task
from ui import state, theme
from ui.common import confirm_delete, load, run, set_undo, show_flash, today
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
        st.form_submit_button("Preview", icon=":material/bolt:", width="stretch",
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
                    on_click=_confirm, args=(repo,), width="stretch")
        right.button("Cancel", key="tq_cancel", on_click=_cancel, width="stretch")


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
        st.button("Add task", type="primary", width="stretch",
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


def _selected(shown: list[Task]) -> list[str]:
    return [t.id for t in shown if st.session_state.get(f"sel_{t.id}")]


def _clear_selection(shown_ids: list[str]) -> None:
    for task_id in shown_ids:
        st.session_state[f"sel_{task_id}"] = False


def _bulk(repo: Repository, action: str, ids: list[str], all_ids: list[str],
          value: object = None) -> None:
    if not ids:
        st.session_state["_flash"] = [("error", "Select at least one task.")]
        return
    ok = False
    if action == "done":
        ok = run(repo.bulk_complete_tasks, ids, ok=f"Completed {len(ids)}.")
    elif action == "assign":
        ok = run(repo.bulk_update_tasks, ids, assignee=value, ok=f"Assigned {len(ids)}.")
    elif action == "tomorrow":
        ok = run(repo.bulk_update_tasks, ids, due_date=today() + timedelta(days=1),
                 ok=f"Moved {len(ids)} to tomorrow.")
    elif action == "archive":
        ok = run(repo.bulk_archive_tasks, ids, ok=f"Archived {len(ids)}. You can restore them.")
        if ok:
            set_undo("bulk_tasks", ids, f"{len(ids)} task(s)")
    if ok:
        _clear_selection(all_ids)


def _select_mode(repo: Repository, shown: list[Task], now: date) -> None:
    """Checkbox list plus a bulk action bar (the bar is filled after the list is drawn)."""
    bar = st.container(key="card_bulkbar")
    all_ids = [t.id for t in shown]
    for task in shown:
        due = f"  ({task.due_date:%d %b})" if task.due_date else ""
        st.checkbox(f"{task.title}{due}", key=f"sel_{task.id}")
    ids = _selected(shown)
    with bar:
        st.caption(f"{len(ids)} selected")
        with st.container(horizontal=True, key="chips_bulk"):
            st.button("Done", icon=":material/check:", key="bk_done", width="content",
                      on_click=_bulk, args=(repo, "done", ids, all_ids))
            st.button("Tomorrow", icon=":material/event:", key="bk_tom", width="content",
                      on_click=_bulk, args=(repo, "tomorrow", ids, all_ids))
            with st.popover("Assign", icon=":material/person:", width="content"):
                for who in ("nick", "natalie", "either"):
                    st.button(who.title(), key=f"bk_as_{who}", width="stretch",
                              on_click=_bulk, args=(repo, "assign", ids, all_ids, who))
            st.button("Archive", icon=":material/inventory_2:", key="bk_arch", width="content",
                      on_click=_bulk, args=(repo, "archive", ids, all_ids))
            if ids:
                confirm_delete("bulk", _delete_selected_action(repo, ids, all_ids),
                               what=f"{len(ids)} task(s)", ok=f"Deleted {len(ids)}.",
                               block=False)


def _delete_selected_action(
    repo: Repository, ids: list[str], all_ids: list[str]
) -> Callable[[], None]:
    def go() -> None:
        repo.bulk_delete_tasks(ids)
        _clear_selection(all_ids)
    return go


def _restore(repo: Repository, task_id: str) -> None:
    run(repo.restore_task, task_id, ok="Task restored.")


def _archived_section(repo: Repository) -> None:
    """Archived tasks, restorable right where tasks live."""
    archived: list[Task] = load(lambda: repo.list_archived_tasks(limit=LIMIT))
    if not archived:
        return
    with st.expander(f"Archived ({len(archived)}) - tap Restore to bring a task back",
                     icon=":material/inventory_2:"):
        for task in archived:
            left, right = st.columns([3, 2], vertical_alignment="center")
            left.write(task.title)
            right.button("Restore", key=f"tr_{task.id}", icon=":material/restore:",
                         on_click=_restore, args=(repo, task.id), width="stretch")


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
    now_day = today()
    shown = filter_tasks(tasks, me, scope != "All", status == "Done")
    shown = sort_tasks(search_tasks(shown, query))
    if not shown:
        theme.empty("Nothing here", "Add one with quick add above.")
    elif st.toggle("Select several", key="t_select"):
        _select_mode(repo, shown, now_day)
        return
    else:
        _render_groups(repo, shown, status)
    _archived_section(repo)
