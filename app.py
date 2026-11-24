"""Household app entry point: navigation, dev banner, login gate."""
from __future__ import annotations

import streamlit as st

from core.repo import Prefs
from ui import nav, quick_dialog, state, theme
from views import (
    activity,
    agenda,
    archive,
    bills,
    dashboard,
    events,
    expenses,
    goals,
    grocery,
    login,
    meals,
    more,
    notes,
    search,
    settings,
    stats,
    tasks,
    templates,
)

MODULES = {m.__name__.split('.')[-1]: m for m in (
    activity, agenda, archive, bills, dashboard, events, expenses, goals, grocery, meals, more,
    notes, search, settings, stats, tasks, templates)}


def _tab_bar(pages: dict[str, st.Page]) -> None:
    """Bottom tab bar (fixed by CSS): Today, Tasks, + (quick add), Grocery, More."""
    with st.container(key="tabbar"):
        cols = st.columns(len(nav.TABS) + 1, gap="small")
        slots = [cols[0], cols[1], cols[3], cols[4]]
        for col, path in zip(slots, nav.TABS, strict=True):
            page = pages[path]
            col.page_link(page, label=page.title, icon=page.icon, width="stretch")
        if cols[2].button("", icon=":material/add:", key="tab_add", help="Quick add"):
            repo, me = state.current_repo(), state.current_user()
            if repo is not None and me is not None:
                quick_dialog.quick_add(repo, me)


def main() -> None:
    st.set_page_config(page_title="Home", page_icon=":house:", layout="centered")
    if state.dev_mode():
        st.warning("DEV MODE: local SQLite data, no cloud, no real login.")
    elif not state.cloud_configured():
        st.error(
            "App is not configured: set SUPABASE_URL, SUPABASE_KEY, NICK_EMAIL and "
            "NATALIE_EMAIL in the app secrets. (For local testing set HOME_APP_DEV=1.)"
        )
        st.stop()
    state.refresh_session()
    signed_in = state.current_repo() is not None
    prefs = state.prefs() if signed_in else Prefs()
    theme.inject(prefs.accent, prefs.compact)
    if not signed_in:
        stubs = [
            st.Page(nav.login_stub(login.render, path), title=title,
                    url_path=path + "_home" if n == 0 else path, default=(n == 0))
            for n, (_g, title, _i, path, _m) in enumerate(nav.PAGES)
        ]
        # The default page is served at "/", so its own /path would be "Page not found":
        # register an alias for it too.
        first = nav.PAGES[0]
        stubs.append(st.Page(nav.login_stub(login.render, first[3] + "_alias"), title=first[1],
                             url_path=first[3]))
        st.navigation(stubs, position="hidden").run()
        return
    start = prefs.start_page if prefs.start_page in nav.url_paths() else nav.PAGES[0][3]
    pages = {
        path: st.Page(MODULES[module].render, title=title, icon=icon,
                      url_path=path + "_home" if path == start else path, default=(path == start))
        for _g, title, icon, path, module in nav.PAGES
    }
    st.session_state[nav.PAGES_KEY] = pages
    # Streamlit serves the default page at "/", so /<its path> would be "Page not found"
    # (old bookmarks, home-screen shortcuts): add an alias that renders the same page.
    default_row = next(r for r in nav.PAGES if r[3] == start)
    alias = nav.login_stub(MODULES[default_row[4]].render, default_row[3] + "_alias")
    alias_page = st.Page(alias, title=default_row[1], icon=default_row[2],
                         url_path=default_row[3])
    current = st.navigation([*pages.values(), alias_page], position="hidden")
    current.run()
    _tab_bar(pages)


main()
