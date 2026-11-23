"""Settings page: storage meter, who is signed in, timezone."""
from __future__ import annotations

import streamlit as st

from core import clock
from core.errors import RepositoryError
from core.repo import Repository
from ui import state
from ui.common import LABELS, flash, friendly, show_flash
from ui.export import build_export_zip

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


EXPORT_KEY = "export_zip"


def _prepare_export(repo: Repository) -> None:
    try:
        st.session_state[EXPORT_KEY] = build_export_zip(repo)
    except RepositoryError as exc:
        st.session_state.pop(EXPORT_KEY, None)
        flash(friendly(exc))


def _export(repo: Repository) -> None:
    st.subheader("Download my data")
    st.caption("A manual backup: a zip with one CSV per list (archived items included). "
               "Nothing is backed up automatically, so download it now and then.")
    st.button("Prepare download", icon=":material/folder_zip:", on_click=_prepare_export,
              args=(repo,), key="export_prepare", use_container_width=True)
    data = st.session_state.get(EXPORT_KEY)
    if data:
        st.download_button("Download zip", data, file_name="home-data.zip",
                           mime="application/zip", icon=":material/download:",
                           key="export_download", use_container_width=True)


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Settings")
    show_flash()
    _storage(repo)
    _export(repo)
    st.subheader("Account")
    st.write(f"Signed in as **{LABELS.get(me, me)}**")
    tz = state.secret("APP_TZ") or clock.DEFAULT_TZ
    st.write(f"Timezone (APP_TZ): **{tz}**")
