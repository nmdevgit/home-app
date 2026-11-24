# Round 4 research: mobile-first redesign + new features

Researcher, 2026-11-24. Verified against the installed **streamlit 1.67.0** / supabase 2.34.1 in `.venv`.

## 0. Findings that explain "basic + mushy" (fix these first)

1. **Streamlit exposes NO theme CSS variables.** `theme.css` uses `var(--secondary-background-color)` and
   `var(--text-color)`; neither exists in the 1.67 frontend bundle (grep of `static/` finds none). So every
   `card_*` container has a **transparent background** and badges' `--c` default is invalid. Cards only show a
   faint border + shadow, which is the "mushy" look. Fix: define our own tokens (section 1.2).
2. **Default vertical gap (1rem) inside cards** + checkbox `min-height` + markdown `<p>` margins = loose,
   airy cards. Tighten the gap inside cards only.
3. **Phone stacking:** `st.columns` stacks at <=640px, so the subtask row `[5,1]` puts the archive icon on
   its own line, and Prev/This week/Next become three full-width rows. 1.67 has `st.columns(..., wrap=False)`
   and `st.container(horizontal=True)`; use them instead of CSS hacks.
4. **Overflow:** `.hh-badge { white-space: nowrap }` with no `max-width/min-width:0`, plus flex children
   without `min-width:0`, lets long badges/titles push wider than 320-375px screens. `st.segmented_control`
   defaults to `width="content"` and never wraps. The Assignee/Priority selectboxes inside expander-in-card
   lose ~2rem of width to nested padding.
5. Nav is the sidebar hamburger on phones: 13 pages, 2 taps to switch. No persistent nav, no global "+".
6. `use_container_width` is deprecated in 1.67; use `width="stretch"`.

## 1. UI/UX redesign (frontend; CSS stays a fixed constant, no user text in HTML)

### 1.1 Available 1.67 building blocks (verified signatures)
| API | Use it for |
|---|---|
| `st.bottom` (public, main area only) | Fixed bottom tab bar |
| `st.navigation(pages, position="hidden"/"top"/"sidebar")` | Hide sidebar nav; drive it from our own bar |
| `st.page_link(page, label, icon, width=)` | Tab bar items + "More" hub tiles |
| `st.container(key=, horizontal=True, wrap=True, gap=, horizontal_alignment=, vertical_alignment=)` | Chip rows / button rows that wrap instead of stacking |
| `st.columns(spec, wrap=False, vertical_alignment=)` | Rows that must stay one line on phones (scroll, never overflow) |
| `st.grid(columns="auto", min_column_width=, wrap=True)` (layouts.py) | Stat tiles / More hub grid (verify name is exported as `st.grid`) |
| `@st.dialog(title, width=, dismissible=, on_dismiss=)` | Global quick-add sheet, confirm delete |
| `st.pills` / `st.segmented_control(width="stretch")` | Filters, assignee picker |
| `st.badge`, `st.metric(chart_data=, border=)`, `st.space(size)`, `st.toast(duration=)` | Small polish |
| `st.context.theme.type` -> "light"/"dark"/None | Pick dark tokens (may lag one rerun; doc says wrong on first load) |
| `st.fragment` | Re-run only a card (checkbox ticks) without whole-page flash |
| config `[theme] headingFont, fontFaces, buttonRadius, borderColor, chartCategoricalColors` | Typography + chart colours |

DOM hooks that exist in 1.67: `.st-key-<key>` on any keyed container/widget; `data-testid` values
`stMain, stMainBlockContainer, stHeader, stSidebar, stBottom, stBottomBlockContainer, stHorizontalBlock,
stVerticalBlock, stColumn, stElementContainer, stLayoutWrapper, stMarkdownContainer, stCheckbox, stExpander,
stExpanderDetails, stPopover, stPopoverBody, stDialog, stTabs, stButtonGroup, stPageLink, stPageLink-NavLink,
stMetric*, stToast, stTopNav*`, `stBaseButton-{primary,secondary,tertiary,...}` (built dynamically; match with `^=`).

### 1.2 Tokens + dark mode (replace top of `ui/theme.css`)
```css
:root {
  --hh-bg:#f1f5f4; --hh-surface:#ffffff; --hh-surface-2:#f6f9f8; --hh-text:#14302b; --hh-muted:#5d716c;
  --hh-line:rgba(20,48,43,.10); --hh-accent:#0f766e; --hh-accent-2:#134e4a; --hh-on-accent:#fff;
  --hh-accent-soft:rgba(15,118,110,.12);
  --hh-nick:#4263eb; --hh-natalie:#d6336c; --hh-either:#7a8793; --hh-ok:#2b8a3e; --hh-warn:#d9480f; --hh-bad:#e03131;
  --hh-shadow:0 1px 2px rgba(15,50,45,.06), 0 10px 24px -16px rgba(15,50,45,.40);
  --hh-r-lg:18px; --hh-r-md:12px; --hh-s1:.25rem; --hh-s2:.5rem; --hh-s3:.75rem; --hh-s4:1rem; --hh-s5:1.5rem;
}
@media (prefers-color-scheme: dark) { :root { /* same as DARK block below */ } }
```
In `theme.py` keep two more CONSTANT strings and inject one after the main CSS, chosen by
`st.context.theme.type` ("dark" -> `DARK`, "light" -> `LIGHT`, None -> nothing, media query decides). This
fixes the case "phone OS light, Streamlit menu set to dark".
```css
/* DARK */ :root { --hh-surface:#17211f; --hh-surface-2:#1d2a27; --hh-text:#e6f0ed; --hh-muted:#9fb3ad;
  --hh-line:rgba(230,240,237,.10); --hh-accent:#2dd4bf; --hh-accent-2:#0f766e; --hh-on-accent:#06201c;
  --hh-accent-soft:rgba(45,212,191,.14); --hh-nick:#748ffc; --hh-natalie:#f06595; --hh-ok:#51cf66;
  --hh-warn:#ff922b; --hh-bad:#ff6b6b; --hh-shadow:0 1px 0 rgba(255,255,255,.04), 0 10px 24px -18px rgba(0,0,0,.9); }
```
Accent picker (feature 7): a dict of ~5 CONSTANT override blocks (`teal, indigo, rose, amber, violet`), each
setting `--hh-accent/--hh-accent-2/--hh-accent-soft` + `[data-testid="stBaseButton-primary"]{background:var(--hh-accent);border-color:var(--hh-accent)}`.
Pref value is validated against the dict keys, never interpolated. (Checkbox/toggle tint stays config primary; accept.)

### 1.3 Layout + spacing + overflow CSS (add to theme.css)
```css
[data-testid="stMainBlockContainer"] { max-width:40rem; padding-top:1rem;
  padding-left:max(.9rem, env(safe-area-inset-left)); padding-right:max(.9rem, env(safe-area-inset-right));
  padding-bottom:calc(6.5rem + env(safe-area-inset-bottom)); }   /* room for bottom bar */
[data-testid="stMain"] { overflow-x:hidden; overflow-x:clip; }    /* clip: no scroll container, sticky still works */
/* Flex children may shrink: the core overflow fix */
[data-testid="stHorizontalBlock"], [data-testid="stColumn"], [data-testid="stVerticalBlock"],
[data-testid="stElementContainer"], [data-testid="stMarkdownContainer"], [data-baseweb="select"] { min-width:0; }
[data-testid="stMarkdownContainer"] p, [data-testid="stCheckbox"] label p { overflow-wrap:anywhere; }
.hh-row { display:flex; flex-wrap:wrap; gap:.3rem; min-width:0; }
.hh-badge { max-width:100%; min-width:0; overflow:hidden; text-overflow:ellipsis; flex:0 1 auto; }
[data-testid="stButtonGroup"] { max-width:100%; overflow-x:auto; scrollbar-width:none; }
[data-testid="stButtonGroup"]::-webkit-scrollbar { display:none; }
[data-testid^="stBaseButton"] p { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* Cards: real surface + tight rhythm */
[class*="st-key-card_"] { background:var(--hh-surface); border:1px solid var(--hh-line);
  border-radius:var(--hh-r-lg); padding:.7rem .8rem; box-shadow:var(--hh-shadow); }
[class*="st-key-card_"] [data-testid="stVerticalBlock"] { gap:.35rem; }
[class*="st-key-card_"] [data-testid="stMarkdownContainer"] p { margin-bottom:0; }
[class*="st-key-card_"] [data-testid="stCheckbox"] label { min-height:2.25rem; }
[class*="st-key-card_"] [data-testid="stExpander"] { border:0; background:var(--hh-surface-2); }
/* Nested padding steals width on phones */
@media (max-width:640px){ [class*="st-key-card_"] [data-testid="stExpanderDetails"] { padding-left:.5rem; padding-right:.5rem; } }
/* Chip row: any container key starting chips_ (must be horizontal=True) */
[class*="st-key-chips_"] { gap:.4rem !important; }
[class*="st-key-chips_"] [data-testid^="stBaseButton"] { min-height:2.25rem; border-radius:99px; padding:0 .8rem; font-size:.85rem; }
.hh-badge { color:var(--c, var(--hh-text)); }    /* replaces broken var(--text-color) */
```
Python-side rules (frontend, all pages):
- Rows that must stay on one line: `st.columns([6,1], wrap=False, vertical_alignment="center")` (subtask row,
  agenda/meals Prev-This week-Next with icon-only Prev/Next + `width="stretch"` middle).
- Small action buttons (Save/Archive/Delete, Add task/Cancel): `with st.container(horizontal=True, key="chips_x")`
  and `st.button(..., width="content")`; they wrap to 2 rows instead of stacking full-width.
- Assignee picker: `st.segmented_control("Who", ["either","nick","natalie"], format_func=LABELS.get, width="stretch")`
  instead of selectbox (3 short labels fit 320px). Priority: `st.pills` with 3 options. Same for Tasks Mine/All, Open/Done.
- Replace every `use_container_width=True` with `width="stretch"`.

### 1.4 Navigation: bottom tab bar + global "+" + More hub (decision)
- `pg = st.navigation(pages, position="hidden")` (keep all `st.Page` objects; add a new `more` page).
- In `app.py`, before `pg.run()`: `with st.bottom: with st.container(horizontal=True, key="tabbar", gap=None, horizontal_alignment="distribute")`
  -> 5 items: Today, Tasks, **+** (st.button -> `@st.dialog("Quick add")`), Grocery, More. Each link wrapped in
  `st.container(key=f"tab_on_{name}" if pg.url_path==name else f"tab_{name}")` so the active tab is styled
  without relying on Streamlit internals. Labels short; icon on top via CSS.
- Quick-add dialog: `st.segmented_control` Task / Grocery / Expense / Event, then the existing parsers
  (`parse_quick_task`, `parse_quick_grocery`), one input + one primary button. Closes with `st.rerun()`.
- "More" page = hub: `st.grid(columns="auto", min_column_width=140)` (fallback: horizontal container) of
  `st.page_link(..., width="stretch")` tiles inside `card_` containers: Agenda, Calendar, Meals, Bills, Expenses,
  Goals, Templates, Notes, Stats, Activity, Archive, Settings + account/log out row (moved from sidebar).
- Desktop keeps working (bar is centered, max-width 40rem). Hide the empty header:
```css
[data-testid="stBottom"] { background:transparent; }
[data-testid="stBottomBlockContainer"] { max-width:40rem; padding:.4rem .6rem calc(.4rem + env(safe-area-inset-bottom)); }
.st-key-tabbar { background:var(--hh-surface); border:1px solid var(--hh-line); border-radius:22px;
  box-shadow:0 -6px 24px -16px rgba(0,0,0,.45); padding:.25rem; flex-wrap:nowrap !important; }
.st-key-tabbar > div { flex:1 1 0; min-width:0; }
.st-key-tabbar [data-testid="stPageLink-NavLink"] { flex-direction:column; gap:.1rem; padding:.35rem 0; border-radius:16px; justify-content:center; }
.st-key-tabbar [data-testid="stPageLink-NavLink"] p { font-size:.68rem; font-weight:650; }
.st-key-tabbar [class*="st-key-tab_on_"] [data-testid="stPageLink-NavLink"] { background:var(--hh-accent-soft); color:var(--hh-accent); }
.st-key-tabbar [data-testid^="stBaseButton"] { border-radius:50%; width:3rem; height:3rem; min-height:3rem; padding:0;
  background:var(--hh-accent); color:var(--hh-on-accent); border:0; box-shadow:0 8px 18px -8px var(--hh-accent); }
```
(Verify in browser that `.st-key-tabbar > div` targets the item wrappers; if not use `[data-testid="stElementContainer"]`/`[data-testid="stLayoutWrapper"]` children.)

### 1.5 Components (new helpers in `ui/theme.py`, all values escaped / ints)
- `hero(...)` v2: person gradient (`hh-hero hh-p-nick|natalie`), greeting, date, progress ring-free bar, plus a row
  of 3 inline mini stats ("3 left", "streak 5d", "$42 owed").
- `tiles([(label, value, tone)])` -> `<div class="hh-tiles">` with
  `.hh-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(6.5rem,1fr));gap:.5rem}` and
  `.hh-tile{background:var(--hh-surface);border:1px solid var(--hh-line);border-radius:14px;padding:.6rem .7rem}`
  `.hh-tile b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}` — never overflows, no columns.
- `countdown_chip(label, days)` -> badge tone by distance (<=3 warn, today accent).
- Section headers with an optional right-aligned tertiary "See all" `st.page_link` (horizontal container).
- Empty states get a material icon via `st.markdown(":material/...:")` + one-line CTA button.
- Undo bar: `card_undo` container rendered at page top for one rerun: text + `st.button("Undo")`.

### 1.6 Safe animation (mount only, GPU-cheap, reduced-motion aware)
```css
@keyframes hh-in { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
[class*="st-key-card_"], .hh-hero, .hh-tile { animation:hh-in .18s ease-out both; }
.hh-fill { transition:width .4s ease; }
[data-testid^="stBaseButton"]:active, [data-testid="stPageLink-NavLink"]:active { transform:scale(.97); }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation:none !important; transition:none !important; } }
```
Do NOT animate height/layout, do not use `:hover` effects for core affordances (touch), do not override
Streamlit's stale-element opacity during reruns. Wrap checkbox-heavy cards in `@st.fragment` so ticking a task
only reruns that card (less flashing).

### 1.7 Typography / config.toml
`[theme] headingFont = "sans-serif"`, `buttonRadius = "full"` (chips/pill buttons), `borderColor = "#dfe7e5"`
(light) / dark equivalent in `[theme.dark]`, `chartCategoricalColors = ["#4263eb","#d6336c","#0f766e"]` (Nick,
Natalie, either) for Stats charts. Keep the system font (no download). Keep `baseFontSize = 15`.
Update `tests/test_theme_css.py` expectations (still: 16px inputs, safe-area, color-mix fallback rule).

## 2. New features (10; 7 in Round 4, 3 parked)

Conventions for every new table (copy 0004 pattern): `id uuid pk default gen_random_uuid()`, `created_by uuid
default auth.uid()`, `created_at timestamptz default now()`, `archived_at timestamptz null`; RLS `is_member()`;
`revoke all ... from anon, authenticated` then grant `select, insert, delete` + column-level `update(...)`;
delete policy as in 0005. Length checks in SQL + `core/rules`. Every list takes `limit`. SQLite mirror + tests.
User text is only ever rendered with native Streamlit elements.

| # | Feature | Tables | Backend | Frontend |
|---|---|---|---|---|
| 1 | Points + streaks | none (derived) | S | S |
| 2 | Activity feed "who did what" | none (derived) | M | S |
| 3 | Shared calendar events + countdowns | `events` | M | M |
| 4 | Savings goals | `goals`, `goal_moves` | M | M |
| 5 | Search everywhere | none | S | S |
| 6 | Bulk actions + Undo | none | S | M |
| 7 | Prefs: accent, pinned shortcuts, default page | `user_prefs` | S | S |
| 8 | Pantry / stock (parked) | `pantry_items` | M | M |
| 9 | Wishlist / gift ideas (parked) | `wishlist` | M | S |
| 10 | Kudos on finished chores (parked) | `kudos` | S | S |

**1. Points + streaks** (derived from `tasks.completed_at/completed_by/priority`).
`core/stats.py`: `POINTS={"high":3,"normal":2,"low":1}`; `points_by_person(done, members, since) -> dict[Person,int]`;
`streak_days(done, person, today, zone) -> int` (consecutive local days with >=1 completion, today optional);
`weekly_leader(...) -> Person|None`. Repo: none new (use `list_done_tasks(since=today-60d, limit=500)`).
UI: hero mini-stat "streak 5d"; Stats page tiles per person (week points, streak, best streak) + weekly winner badge.

**2. Activity feed.** Contract: `@dataclass Activity(at: datetime, person: Person|None, verb: str, kind: str, title: str, ref_id: str)`;
`list_activity(since: datetime, limit: int = 50) -> list[Activity]` merging, each source capped at `limit`:
tasks completed (completed_at, completed_by), tasks added (created_at, created_by), grocery added (added_by),
expenses (created_by), notes updated (updated_at, created_by), goal moves, events added. Newest first, merge in
Python. Map user id -> person via `list_members()`. UI: Today "Recently" card (last 5) + Activity page grouped by
day ("Natalie finished *Vacuum*  2h ago"); title via `st.write`, not HTML.

**3. Events (shared calendar, birthdays, countdowns).**
`events(title text 1..120, day date, start_time time null, who text check in ('nick','natalie','both'),
notes text <=1000 default '', recurrence text check in ('none','weekly','monthly','yearly') default 'none',
remind_days int 0..60 default 0)`. Update grants: all of those + archived_at.
`core/rules.event_occurrences(event, start, end) -> list[date]` (yearly handles Feb 29 -> Feb 28).
Repo: `list_events(start, end, limit=300) -> list[EventOccurrence]` (fetch `day<=end and (recurrence<>'none' or day>=start)`, expand),
`upcoming_events(today, days=60, limit=10)`, `add_event`, `update_event`, `archive_event`, `restore_event`, `delete_event`.
UI: Agenda merges events (icon `:material/event:`); new Calendar page = month list (no grid widget: one card per
day with entries, `st.segmented_control` Month/Week); Today "Coming up" countdown chips (incl. events whose
`day - remind_days <= today`); quick-add dialog "Event" tab.

**4. Savings goals.** `goals(name 1..80, target_cents int 1..1e9, due_date date null, icon text check in fixed
list default 'savings')`; `goal_moves(goal_id uuid fk on delete cascade, amount_cents int -1e9..1e9 <>0,
person text check nick/natalie, day date, note text <=120)`. Dataclasses `Goal(..., saved_cents:int)`,
`GoalMove`. Repo: `list_goals(limit)` (two queries: goals, then moves `in goal_ids` limit 2000, sum in Python),
`add_goal`, `update_goal`, `archive_goal`, `delete_goal`, `add_goal_move(goal_id, amount_cents, person, note="")`,
`list_goal_moves(goal_id, limit=50)`, `delete_goal_move`. `rules.goal_pace(goal, today) -> per-week cents needed`.
UI: Goals page: card per goal with big %, bar, "$x of $y", "need $z/week", chip row `+$10 +$50 +$100 Custom`
(custom -> popover number_input), history expander. Today tile "Holiday fund 62%".

**5. Search everywhere.** `@dataclass SearchHit(kind, id, title, snippet, page)`; `search(query, limit=40)`.
Validate: strip, 2..60 chars; **remove `,()*%_\\` before building PostgREST `ilike`/`or=` filters** (or-filter
injection). Sources: tasks(title, notes), grocery(name), notes(title, body), meals(title), templates(name, items),
bills(name), events(title), goals(name); 8 per source, non-archived. SQLite: `LIKE ? ESCAPE '\\'`.
UI: search input at top of More hub + "/search" page; hits grouped by kind with `st.page_link` to the page.

**6. Bulk actions + Undo.** Repo: `bulk_complete_tasks(ids) -> int` (calls complete logic per id, max 50),
`bulk_update_tasks(ids, **fields) -> int` (assignee, due_date, priority only; one `in` update),
`bulk_archive_tasks(ids) -> int`, `bulk_delete_tasks(ids) -> int`; `undo_complete(task_id) -> Task` (reopen; if a
recurring occurrence was spawned and is still open+untouched, delete it); `restore_meal/bill/note/expense/template`
(only task/grocery restore exist today). UI: Tasks "Select" toggle -> checkboxes keyed `sel_<id>`, sticky action
chips row (Done, Assign to..., Move to tomorrow, Archive, Delete-with-confirm dialog). Undo: after complete/archive
put `("undo", kind, id, label)` in session_state; next render shows `card_undo` bar with Undo button for that run
only. Delete stays permanent behind `@st.dialog` confirm (no undo).

**7. Prefs (accent, pinned shortcuts, default page, compact).** `user_prefs(user_id uuid pk default auth.uid(),
accent text check in ('teal','indigo','rose','amber','violet') default 'teal', pinned text default '' (csv of
page keys, <=6, validated against a fixed set), start_page text default 'today', compact bool default false,
updated_at timestamptz)`. RLS: `user_id = (select auth.uid())` for select/insert/update (per-person, not household).
Repo: `get_prefs() -> Prefs` (defaults if no row), `save_prefs(**fields) -> Prefs` (upsert). SQLite: keyed by person.
UI: Settings "Look and feel": accent swatches (`st.pills`), pinned shortcuts (`st.multiselect` max 6), dark mode
note ("follows phone; override in ... menu > Settings"). Today shows pinned shortcuts as a chip row of page links.
Load prefs once per session into `st.session_state["prefs"]`, refresh after save.

Parked (Round 5): **8 Pantry** `pantry_items(name, category, qty int, low_at int, unit)`, "+/-" chips, low ->
`add_grocery`. **9 Wishlist** `wishlist(title, for_person, price_cents, url text, status idea/bought, secret bool)`;
secret gifts need RLS `for_person <> my_person()` (L if done properly). **10 Kudos** `kudos(task_id fk, from_person,
kind in ('thanks','star','heart'))`, one tap on a finished chore in the activity feed.

## 3. Task breakdown (each = one agent pass; ordered)

**PM first (contract):** add to `core/repo.py`: `Activity, EventItem, EventOccurrence, Goal, GoalMove, SearchHit,
Prefs` dataclasses + methods listed in features 2-7; `EXPORT_TABLES += ("events","goals","goal_moves")`
(not user_prefs). Frontend must feature-detect nothing; it codes against the contract and uses the fake repo in
`tests/ui_fake.py` (backend adds the new methods to it in B1).

### Backend (sonnet; `core/`, `supabase/`, `tests/`)
- **B0** (in flight) `0005_allow_delete.sql` + delete_* + purge_archived in both repos.
- **B1 Derived stats + activity + search** (no SQL): `core/stats.py` points/streaks/leader; `list_activity`,
  `search` in SQLite + Supabase repos (filter sanitiser in `core/rules`), `tests/ui_fake.py` stubs for ALL new
  contract methods (so frontend can start). Tests incl. injection chars and streak across midnight APP_TZ.
- **B2 Bulk + undo + restores**: `bulk_*`, `undo_complete`, `restore_meal/bill/note/expense/template`, tests.
- **B3 Prefs**: `0006_round4.sql` part 1 (`user_prefs` + RLS by auth.uid + grants), `get_prefs/save_prefs` (upsert), tests.
- **B4 Events**: 0006 part 2 (`events`), `rules.event_occurrences`, repo methods, export, tests (yearly Feb 29, weekly expansion limits).
- **B5 Goals**: 0006 part 3 (`goals`, `goal_moves`, cascade), repo methods, `rules.goal_pace`, export, tests.
  One migration file `0006_round4.sql` written incrementally by B3-B5, run by Nick after 0005.

### Frontend (sonnet; `app.py`, `views/`, `ui/`, `.streamlit/config.toml`, UI tests)
- **F1 Design system** (no backend deps): tokens + dark/light constant blocks + accent blocks, overflow/spacing
  CSS (1.2-1.3, 1.6), `tiles/countdown_chip/hero v2/undo bar` helpers, config.toml additions, `width="stretch"`
  sweep, `columns(wrap=False)` for subtask + week-nav rows, segmented assignee/pills priority. Update theme tests.
  Check at 320/375/412px in dev mode (`HOME_APP_DEV=1`).
- **F2 Nav shell**: `position="hidden"`, bottom tab bar via `st.bottom`, quick-add `@st.dialog` (Task/Grocery now;
  Expense/Event tabs added in F4), More hub page with tile grid + account row (sidebar removed).
- **F3 Today redesign** (needs B1): hero v2 with streak, tiles row (left today / overdue / bills due / owed),
  pinned shortcuts chip row (static default until B3), Overdue/Due today cards in `@st.fragment`, "Coming up"
  (bills now, events after B4), "Recently" activity card, dinner card.
- **F4 Tasks bulk + Undo + Search + Activity/Stats** (needs B1, B2): select mode + action chips + delete confirm
  dialog, undo bar on Tasks/Grocery/Today, Search page, Activity page, Stats points/streak tiles.
- **F5 Calendar + Goals + Prefs** (needs B3-B5): Calendar page + Agenda merge + countdowns + quick-add Event tab;
  Goals page + Today goal tile; Settings "Look and feel" (accent, pins, start page) applied in `app.py`.

Total: backend 5 passes (+B0), frontend 5 passes. Parallelism: B1 and F1/F2 start together; F3 after B1; F4 after
B2; F5 after B3-B5. Nick must run `0005` then `0006` in Supabase before deploying F5 code.

## 4. Risks / verify in browser
- `st.bottom` items' wrapper DOM (adjust `.st-key-tabbar > div` selector); bottom bar must not cover the last
  card (padding-bottom 6.5rem) or the iOS keyboard (bottom bar rises with keyboard on iOS; acceptable).
- `st.context.theme.type` can be stale on first load and right after a theme switch: media query is the base,
  the injected block only corrects mismatch.
- `st.grid` availability as a public command: confirm `hasattr(st, "grid")`; fallback horizontal container.
- Dialog + `st.rerun()` from callbacks: call `st.rerun()` in the dialog body after the action, not in `on_click`.
- Free tier: all new features are text rows (<1 KB each); activity/search are capped multi-query reads (~8 small
  queries) - fine for 2 users.
