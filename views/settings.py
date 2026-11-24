"""Settings page: storage meter, who is signed in, timezone."""
from __future__ import annotations

import streamlit as st

from core import clock
from core.errors import RepositoryError
from core.repo import Repository
from ui import nav, state, theme
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


ACCENT_NAMES = tuple(theme.ACCENTS)
PIN_MAX = 6


def _save_look(repo: Repository) -> None:
    get = st.session_state.get
    pins = [p for p in get("lk_pins", []) if p in nav.url_paths()][:PIN_MAX]
    try:
        state.save_prefs(accent=get("lk_accent") or "teal", pinned=tuple(pins),
                         start_page=get("lk_start") or "today", compact=bool(get("lk_compact")))
    except RepositoryError as exc:
        flash(friendly(exc))
        return
    flash("Look and feel saved.", "ok")


def _look(repo: Repository) -> None:
    prefs = state.prefs()
    st.subheader("Look and feel")
    st.caption("Only you see these; Nick and Natalie each have their own.")
    titles = {p[3]: p[1] for p in nav.PAGES}
    st.segmented_control("Accent colour", ACCENT_NAMES, default=prefs.accent,
                         format_func=str.title, key="lk_accent", width="stretch")
    st.multiselect("Shortcuts on Today (max 6)", [p for p in titles if p != "today"],
                   default=[p for p in prefs.pinned if p in titles],
                   format_func=titles.get, max_selections=PIN_MAX, key="lk_pins")
    st.selectbox("Start page", list(titles), index=list(titles).index(
        prefs.start_page if prefs.start_page in titles else "today"),
        format_func=titles.get, key="lk_start")
    st.toggle("Compact layout", value=prefs.compact, key="lk_compact")
    st.button("Save look and feel", type="primary", width="stretch", on_click=_save_look,
              args=(repo,), key="lk_save")


def _export(repo: Repository) -> None:
    st.subheader("Download my data")
    st.caption("A manual backup: a zip with one CSV per list (archived items included). "
               "Nothing is backed up automatically, so download it now and then.")
    st.button("Prepare download", icon=":material/folder_zip:", on_click=_prepare_export,
              args=(repo,), key="export_prepare", width="stretch")
    data = st.session_state.get(EXPORT_KEY)
    if data:
        st.download_button("Download zip", data, file_name="home-data.zip",
                           mime="application/zip", icon=":material/download:",
                           key="export_download", width="stretch")


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Settings")
    show_flash()
    _look(repo)
    _storage(repo)
    _export(repo)
    st.subheader("Account")
    st.write(f"Signed in as **{LABELS.get(me, me)}**")
    tz = state.secret("APP_TZ") or clock.DEFAULT_TZ
    st.write(f"Timezone (APP_TZ): **{tz}**")
