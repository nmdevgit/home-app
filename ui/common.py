"""Shared UI helpers: error handling, flash messages, task widgets."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import streamlit as st

from core import clock
from core.errors import RepositoryError, ValidationError
from ui import state

LABELS = {"nick": "Nick", "natalie": "Natalie", "either": "Either"}
RECURRENCES = ("none", "daily", "weekly", "monthly")
FLASH_KEY = "_flash"


def friendly(exc: RepositoryError) -> str:
    """Turn a repository error into a short message for humans."""
    if isinstance(exc, ValidationError):
        return str(exc)
    return f"Something went wrong ({type(exc).__name__}). Please try again: {exc}"


def flash(message: str, kind: str = "error") -> None:
    st.session_state.setdefault(FLASH_KEY, []).append((kind, message))


UNDO_KEY = "_undo"
UNDO_SECONDS = 90


def set_undo(kind: str, ref: str | list[str], title: str) -> None:
    """Remember the last complete/archive so every page can offer Undo for ~90s.

    kind: 'complete' | 'archive' (a task) | 'grocery' (ref may be a list of ids) | any
    ArchivedKind ('meal', 'bill', 'note', 'expense', 'template', 'event', 'goal', 'subtask').
    """
    st.session_state[UNDO_KEY] = (kind, ref, title, datetime.now().timestamp())


def archive_item(kind: str, action: Callable[..., Any], item_id: str, title: str,
                 ok: str) -> bool:
    """Run an archive action and queue the persistent Undo bar for it."""
    if run(action, item_id, ok=ok):
        set_undo(kind, item_id, title)
        return True
    return False


def _do_undo() -> None:
    entry = st.session_state.pop(UNDO_KEY, None)
    repo = state.current_repo()
    if not entry or repo is None:
        return
    kind, ref = entry[0], entry[1]
    if kind == "complete":
        run(repo.undo_complete, ref, ok="Undone.")
    elif kind == "archive":
        run(repo.restore_task, ref, ok="Restored.")
    elif kind in ("grocery", "bulk_tasks"):
        restore = repo.restore_grocery if kind == "grocery" else repo.restore_task
        for item_id in [ref] if isinstance(ref, str) else ref:
            run(restore, item_id)
        flash("Restored.", "ok")
    else:
        run(repo.restore_item, kind, ref, ok="Restored.")


def _dismiss_undo() -> None:
    st.session_state.pop(UNDO_KEY, None)


def render_undo() -> None:
    """Small Undo bar for the most recent complete/archive (expires after 90 seconds)."""
    entry = st.session_state.get(UNDO_KEY)
    if not entry:
        return
    kind, _tid, title, stamp = entry
    if datetime.now().timestamp() - stamp > UNDO_SECONDS:
        _dismiss_undo()
        return
    verb = "Completed" if kind == "complete" else "Archived"
    with st.container(key="undo_bar"):
        text_col, undo_col, x_col = st.columns([3, 3, 1], vertical_alignment="center", gap="small")
        text_col.caption(f"{verb}: {title}"[:60])
        undo_col.button("Undo", key="undo_btn", on_click=_do_undo, icon=":material/undo:")
        x_col.button("", key="undo_x", icon=":material/close:", on_click=_dismiss_undo,
                     help="Dismiss")


def show_flash() -> None:
    """Render and clear queued messages (callbacks queue them, pages show them)."""
    render_undo()
    for kind, message in st.session_state.pop(FLASH_KEY, []):
        if kind == "error":
            st.error(message)
        else:
            st.toast(message, icon=":material/check_circle:")


def run(action: Callable[..., Any], *args: Any, ok: str | None = None, **kwargs: Any) -> bool:
    """Call a repo action, queueing a friendly error on failure. Returns success."""
    try:
        action(*args, **kwargs)
    except RepositoryError as exc:
        flash(friendly(exc))
        return False
    if ok:
        flash(ok, "ok")
    return True


def load(fetch: Callable[[], list[Any]]) -> list[Any]:
    """Fetch a list for display; on failure show an error and return []."""
    try:
        return fetch()
    except RepositoryError as exc:
        st.error(friendly(exc))
        return []


def today() -> date:
    """Today in APP_TZ; stops the page with a clear error if APP_TZ is invalid."""
    try:
        return clock.today(state.secret("APP_TZ") or None)
    except ValidationError as exc:
        st.error(f"Server configuration problem: APP_TZ is invalid ({exc}).")
        st.stop()


def now_local() -> datetime:
    """Current time in APP_TZ (stops the page with a clear error if APP_TZ is invalid)."""
    try:
        return datetime.now(clock.get_zone(state.secret("APP_TZ") or None))
    except ValidationError as exc:
        st.error(f"Server configuration problem: APP_TZ is invalid ({exc}).")
        st.stop()


def run_value(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Like run() but returns the action's result, or None after queueing an error."""
    try:
        return action(*args, **kwargs)
    except RepositoryError as exc:
        flash(friendly(exc))
        return None


def confirm_delete(key: str, action: Callable[..., Any], *args: Any, what: str = "this",
                   ok: str = "Deleted.", label: str = "Delete", block: bool = True) -> None:
    """Danger popover: 'Delete forever?' then a red confirm button calling `action(*args)`.

    The wrapper container key starts with `del_` so theme.css can paint it red.
    """
    def _go() -> None:
        run(action, *args, ok=ok)

    with st.container(key=f"del_{key}"):
        width = "stretch" if block else "content"
        with st.popover(label, icon=":material/delete_forever:", width=width):
            st.markdown(f"**Delete forever?**  \nThis permanently removes {what}. "
                        "It cannot be undone.")
            st.button("Yes, delete forever", key=f"del_{key}_yes", on_click=_go,
                      width="stretch")
