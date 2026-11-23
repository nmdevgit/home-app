"""Settings page: storage meter, who is signed in, timezone."""
from __future__ import annotations

import streamlit as st

from core import clock
from core.errors import RepositoryError
from core.repo import Repository
from ui import state
from ui.common import LABELS, friendly

WARN_AT = 0.8
MB = 1024 * 1024


def _storage(repo: Repository) -> None:
    st.subheader("Storage")
    try:
        usage = repo.storage_usage()
    except RepositoryError as exc:
        st.error(f"Could not read storage usage. {friendly(exc)}")
        return
    frac = min(1.0, usage.used_bytes / usage.limit_bytes) if usage.limit_bytes else 0.0
    st.progress(frac)
    st.write(f"{usage.used_bytes / MB:.1f} MB used of {usage.limit_bytes / MB:.0f} MB "
             f"({frac:.0%})")
    if frac >= WARN_AT:
        st.warning("Storage is over 80% full. Archived data still counts; tell Nick.")


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Settings")
    _storage(repo)
    st.subheader("Account")
    st.write(f"Signed in as **{LABELS.get(me, me)}**")
    tz = state.secret("APP_TZ") or clock.DEFAULT_TZ
    st.write(f"Timezone (APP_TZ): **{tz}**")
