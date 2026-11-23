"""Household app entry point: navigation, dev banner, login gate."""
from __future__ import annotations

import streamlit as st

from ui import state
from views import dashboard, grocery, login, tasks


def _logout() -> None:
    state.sign_out()


def _sidebar_account() -> None:
    me = state.current_user()
    with st.sidebar:
        st.write(f"Signed in as **{(me or '').title()}**")
        st.button("Log out", on_click=_logout, use_container_width=True)


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
    if state.current_repo() is None:
        st.navigation([st.Page(login.render, title="Sign in", url_path="login")]).run()
        return
    _sidebar_account()
    pages = [
        st.Page(dashboard.render, title="Today", icon=":material/today:",
                url_path="today", default=True),
        st.Page(tasks.render, title="Tasks", icon=":material/checklist:", url_path="tasks"),
        st.Page(grocery.render, title="Grocery", icon=":material/shopping_cart:",
                url_path="grocery"),
    ]
    st.navigation(pages).run()


main()
