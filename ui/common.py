"""Shared UI helpers: error handling, flash messages, task widgets."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import streamlit as st

from core import clock
from core.errors import RepositoryError, ValidationError
from core.repo import Repository, Task
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


def show_flash() -> None:
    """Render and clear queued messages (callbacks queue them, pages show them)."""
    for kind, message in st.session_state.pop(FLASH_KEY, []):
        if kind == "error":
            st.error(message)
        elif kind == "toast":
            st.toast(message)
        else:
            st.success(message)


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


def _toggle_task(repo: Repository, task: Task, key: str) -> None:
    if st.session_state.get(key):
        run(repo.complete_task, task.id)
    else:
        run(repo.reopen_task, task.id)


def task_checkbox(repo: Repository, task: Task, prefix: str) -> None:
    """One-line task with a big checkbox that completes/reopens on tick."""
    key = f"{prefix}_chk_{task.id}"
    due = f" - due {task.due_date:%a %d %b}" if task.due_date else ""
    repeat = f" (repeats {task.recurrence})" if task.recurrence != "none" else ""
    mark = ":red[**HIGH**] " if task.priority == "high" else ""
    low = " (low)" if task.priority == "low" else ""
    label = f"{mark}{task.title}{due}{repeat}{low}"
    st.checkbox(
        label,
        value=task.status == "done",
        key=key,
        on_change=_toggle_task,
        args=(repo, task, key),
    )


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
