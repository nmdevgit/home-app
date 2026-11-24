"""Design system: one scoped CSS block plus small HTML helpers.

Safety rule: the CSS is a fixed constant. Any helper that builds HTML escapes every
dynamic value; user-provided text (titles, notes, names) is rendered with native
Streamlit components instead, never put into HTML.
"""
from __future__ import annotations

import html
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

# Person colours: Nick = ink blue, Natalie = berry, Either = slate.
PERSON_NAMES = {"nick": "Nick", "natalie": "Natalie", "either": "Either"}
TONES = frozenset({"neutral", "ok", "warn", "bad", "nick", "natalie", "either", "accent"})

CSS = "<style>" + (Path(__file__).with_name("theme.css")).read_text(encoding="utf-8") + "</style>"


# Accent presets: fixed constants. The pref value only SELECTS a key; it is never interpolated.
_PRESETS = {  # name: (accent, darker accent, "r,g,b" for the soft tint)
    "indigo": ("#4c6ef5", "#364fc7", "76,110,245"),
    "rose": ("#d6336c", "#a61e4d", "214,51,108"),
    "amber": ("#e67700", "#b35c00", "230,119,0"),
    "violet": ("#7048e8", "#5f3dc4", "112,72,232"),
}
ACCENTS: dict[str, str] = {"teal": ""} | {
    name: f":root{{--hh-accent:{c1};--hh-accent-2:{c2};--hh-accent-soft:rgba({rgb},.14);}}"
    for name, (c1, c2, rgb) in _PRESETS.items()
}
_ACCENT_BUTTONS = (
    '[data-testid="stBaseButton-primary"]{background:var(--hh-accent);'
    "background:linear-gradient(135deg,var(--hh-accent),var(--hh-accent-2));}"
    ".hh-hero{background:var(--hh-accent-2);}"
)
COMPACT_CSS = (
    '[class*="st-key-card_"]{padding:.35rem .5rem;}'
    '[data-testid="stCheckbox"] label{min-height:2.75rem;}'
    '[data-testid="stVerticalBlock"]{gap:.25rem;}'
)


def inject(accent: str = "teal", compact: bool = False) -> None:
    """Inject the fixed CSS once per page render, plus a validated accent preset."""
    extra = ACCENTS.get(accent, "")
    if extra:
        extra += _ACCENT_BUTTONS
    if compact:
        extra += COMPACT_CSS
    st.markdown(CSS + (f"<style>{extra}</style>" if extra else ""), unsafe_allow_html=True)


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


def tiles(items: list[tuple[str, str, str]]) -> None:
    """Row of stat tiles: (value, label, tone). Values are escaped."""
    body = "".join(
        f'<div class="hh-tile hh-t-{_tone(tone)}"><b>{esc(value)}</b>'
        f"<span>{esc(label)}</span></div>"
        for value, label, tone in items
    )
    html_block(f'<div class="hh-tiles">{body}</div>')


def bar(percent: float) -> str:
    """Progress bar markup (pure number, clamped 0..100)."""
    pct = int(max(0, min(100, percent)))
    return f'<div class="hh-bar"><i style="width:{pct}%"></i></div>'


def hero2(greeting: str, date_text: str, done: int, total: int, person: str,
          stats: list[str]) -> None:
    """Person-coloured greeting card with progress and a row of mini stats."""
    pct = int(100 * done / total) if total else 100
    line = f"{int(done)} of {int(total)} done today" if total else "Nothing due today"
    key = person if person in PERSON_NAMES else "either"
    chips = "".join(f"<span>{esc(x)}</span>" for x in stats if x)
    html_block(
        f'<div class="hh-hero hh-p-{key}"><div class="hh-hi">{esc(greeting)}</div>'
        f'<div class="hh-date">{esc(date_text)}</div>'
        f'<div class="hh-prog">{esc(line)}</div>'
        f'<div class="hh-track"><div class="hh-fill" style="width:{pct}%"></div></div>'
        f'<div class="hh-herostats">{chips}</div></div>'
    )


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    return f"{start:%d %b} - {end:%d %b %Y}"
