"""Login page: email/password (cloud) or person picker (dev mode)."""
from __future__ import annotations

import streamlit as st

from core.errors import RepositoryError
from ui import state
from ui.common import LABELS, friendly


def _dev_login() -> None:
    st.info("Pick who you are. No password needed in dev mode.")
    person = st.radio("I am", ["nick", "natalie"], format_func=LABELS.get, horizontal=True)
    if st.button("Continue", type="primary", use_container_width=True):
        state.start_dev_session(person)
        st.rerun()


def _cloud_login() -> None:
    with st.form("login"):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if not submitted:
        return
    if not email or not password:
        st.error("Enter your email and password.")
        return
    try:
        state.start_cloud_session(email, password)
    except RepositoryError as exc:
        st.error(friendly(exc))
        return
    st.rerun()


def render() -> None:
    st.title("Home")
    if state.dev_mode():
        _dev_login()
    else:
        _cloud_login()
