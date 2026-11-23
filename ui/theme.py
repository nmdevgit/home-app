"""Design system: one scoped CSS block plus small HTML helpers.

Safety rule: the CSS is a fixed constant. Any helper that builds HTML escapes every
dynamic value; user-provided text (titles, notes, names) is rendered with native
Streamlit components instead, never put into HTML.
"""
from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

# Person colours: Nick = ink blue, Natalie = berry, Either = slate.
PERSON_NAMES = {"nick": "Nick", "natalie": "Natalie", "either": "Either"}
TONES = frozenset({"neutral", "ok", "warn", "bad", "nick", "natalie", "either", "accent"})

CSS = """
<style>
:root {
  --hh-nick: #4263eb; --hh-natalie: #d6336c; --hh-either: #7a8793;
  --hh-ok: #2b8a3e; --hh-warn: #d9480f; --hh-bad: #e03131; --hh-accent: #0f766e;
  --hh-line: color-mix(in srgb, var(--text-color) 11%, transparent);
}
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 42rem; }
h1 { letter-spacing: -0.02em; font-weight: 750; }
h2, h3 { letter-spacing: -0.01em; }

/* Cards: any container created with key="card_..." */
[class*="st-key-card_"] {
  background: var(--secondary-background-color);
  border: 1px solid var(--hh-line); border-radius: 18px;
  padding: 0.35rem 0.5rem;
  box-shadow: 0 1px 2px rgba(15, 50, 45, 0.06), 0 10px 24px -14px rgba(15, 50, 45, 0.35);
}
[class*="st-key-card_"] [data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 14px;
}

/* Tap targets */
[data-testid^="stBaseButton"] { min-height: 2.75rem; border-radius: 12px; font-weight: 600; }
[data-testid="stCheckbox"] label { min-height: 2.5rem; align-items: center; }
[data-testid="stCheckbox"] label p { font-size: 1.02rem; }
[data-testid="stExpander"] summary { min-height: 2.75rem; }
[data-testid="stExpander"] { border-radius: 14px; }
input, textarea, [data-baseweb="select"] > div { border-radius: 12px !important; }

/* Hero */
.hh-hero {
  background: linear-gradient(135deg, #0f766e 0%, #134e4a 100%); color: #fff;
  border-radius: 22px; padding: 1.25rem 1.25rem 1.1rem; margin-bottom: 1rem;
  box-shadow: 0 14px 30px -16px rgba(19, 78, 74, 0.8);
}
.hh-hero .hh-hi { font-size: 1.7rem; font-weight: 780; letter-spacing: -0.02em; line-height: 1.15; }
.hh-hero .hh-date { opacity: 0.8; font-size: 0.95rem; margin-top: 0.15rem; }
.hh-hero .hh-prog { margin-top: 0.9rem; font-size: 0.92rem; font-weight: 600; }
.hh-track { height: 10px; border-radius: 99px; background: rgba(255,255,255,0.22); margin-top: 0.4rem; }
.hh-fill { height: 100%; border-radius: 99px; background: #fff; }

/* Section headings */
.hh-section { display: flex; align-items: center; gap: 0.5rem; margin: 1.3rem 0 0.4rem;
  font-size: 1.1rem; font-weight: 720; letter-spacing: -0.01em; }
.hh-count { font-size: 0.78rem; font-weight: 700; padding: 0.05rem 0.5rem; border-radius: 99px;
  background: var(--hh-line); }
.hh-section.hh-bad .hh-count { background: color-mix(in srgb, var(--hh-bad) 18%, transparent);
  color: var(--hh-bad); }

/* Badges and avatars */
.hh-row { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; margin: 0.1rem 0 0.3rem; }
.hh-badge { --c: var(--text-color); display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.12rem 0.6rem; border-radius: 99px; font-size: 0.78rem; font-weight: 650; color: var(--c);
  background: color-mix(in srgb, var(--c) 14%, transparent); white-space: nowrap; }
.hh-t-ok { --c: var(--hh-ok); } .hh-t-warn { --c: var(--hh-warn); } .hh-t-bad { --c: var(--hh-bad); }
.hh-t-nick { --c: var(--hh-nick); } .hh-t-natalie { --c: var(--hh-natalie); }
.hh-t-either { --c: var(--hh-either); } .hh-t-accent { --c: var(--hh-accent); }
.hh-av { display: inline-flex; align-items: center; justify-content: center; width: 1.25rem;
  height: 1.25rem; border-radius: 50%; color: #fff; font-size: 0.7rem; font-weight: 800;
  background: var(--c); }

/* Empty states and big numbers */
.hh-empty { text-align: center; padding: 1.4rem 1rem; border: 1.5px dashed var(--hh-line);
  border-radius: 18px; }
.hh-empty b { display: block; font-size: 1.05rem; margin-bottom: 0.2rem; }
.hh-empty span { opacity: 0.7; font-size: 0.92rem; }
.hh-balance { text-align: center; padding: 1.2rem 0.5rem; }
.hh-balance .hh-amt { font-size: 2.3rem; font-weight: 800; letter-spacing: -0.03em; }
.hh-balance .hh-who { opacity: 0.75; font-size: 0.95rem; }

@media (max-width: 640px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .hh-hero .hh-hi { font-size: 1.45rem; }
}
</style>
"""  # noqa: E501


def inject() -> None:
    """Inject the fixed CSS block once per page render."""
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def html_block(markup: str) -> None:
    """Render markup produced by the helpers in this module (all values escaped)."""
    st.markdown(markup, unsafe_allow_html=True)


def _tone(tone: str) -> str:
    return tone if tone in TONES else "neutral"


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="hh-badge hh-t-{_tone(tone)}">{esc(text)}</span>'


def avatar(person: str) -> str:
    name = PERSON_NAMES.get(person, "Either")
    key = person if person in PERSON_NAMES else "either"
    return f'<span class="hh-av hh-t-{key}">{esc(name[0])}</span>'


def person_badge(person: str) -> str:
    key = person if person in PERSON_NAMES else "either"
    return (f'<span class="hh-badge hh-t-{key}">{avatar(key)}{esc(PERSON_NAMES[key])}</span>')


def due_badge(due: date | None, today: date) -> str:
    """Pill for a due date: Overdue Nd / Today / Tomorrow / weekday date."""
    if due is None:
        return ""
    gap = (due - today).days
    if gap < 0:
        return badge(f"Overdue {-gap}d", "bad")
    if gap == 0:
        return badge("Due today", "warn")
    if gap == 1:
        return badge("Tomorrow", "accent")
    if gap < 7:
        return badge(f"{due:%a %d %b}", "neutral")
    return badge(f"{due:%d %b}", "neutral")


def priority_badge(priority: str) -> str:
    if priority == "high":
        return badge("High priority", "bad")
    if priority == "low":
        return badge("Low", "neutral")
    return ""


def pills(*items: str) -> None:
    """A wrapping row of pre-built badge strings (empty ones are skipped)."""
    body = "".join(i for i in items if i)
    if body:
        html_block(f'<div class="hh-row">{body}</div>')


def section(title: str, count: int | None = None, tone: str = "") -> None:
    badge_html = f'<span class="hh-count">{int(count)}</span>' if count is not None else ""
    cls = " hh-bad" if tone == "bad" else ""
    html_block(f'<div class="hh-section{cls}">{esc(title)}{badge_html}</div>')


def empty(title: str, hint: str = "") -> None:
    hint_html = f"<span>{esc(hint)}</span>" if hint else ""
    html_block(f'<div class="hh-empty"><b>{esc(title)}</b>{hint_html}</div>')


def hero(greeting: str, date_text: str, done: int, total: int) -> None:
    """Greeting card with 'x of y done today' progress."""
    pct = int(100 * done / total) if total else 100
    line = f"{int(done)} of {int(total)} done today" if total else "Nothing due today"
    html_block(
        f'<div class="hh-hero"><div class="hh-hi">{esc(greeting)}</div>'
        f'<div class="hh-date">{esc(date_text)}</div>'
        f'<div class="hh-prog">{esc(line)}</div>'
        f'<div class="hh-track"><div class="hh-fill" style="width:{pct}%"></div></div></div>'
    )


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start:%d %b} - {end:%d %b %Y}"
