# Research: Home App (Streamlit + Supabase, free tier)

Researcher notes, 2026-11-23. Items marked "verify" were not confirmed against current source/docs.

---

## 1. Auth (Supabase email+password in Streamlit)

**Recommendation: one supabase client per browser session, kept in `st.session_state`; login with `sign_in_with_password`; manual token refresh at top of each run; accept re-login after a full browser reload. No cookies.**

- **Never** put the per-user client in `st.cache_resource` / module global. Those are shared across all sessions, so Nick's JWT would leak into Natalie's session. (A forum thread suggests this pattern; it is wrong for multi-user: https://discuss.streamlit.io/t/how-to-properly-cache-supabases-access-and-refresh-token/90849)
- After sign-in (or `set_session`), supabase-py listens to auth events (SIGNED_IN / TOKEN_REFRESHED / SIGNED_OUT) and swaps the PostgREST `Authorization` header to the user JWT, so RLS sees `auth.uid()`. (supabase-py PR #1171 / #766, https://github.com/supabase/supabase-py/pull/766)
- Refresh tokens are single-use, never expire; 10 s reuse interval (https://supabase.com/docs/guides/auth/sessions). Access token default ~1 h.

```python
# core/auth.py (sketch, verify option names against installed supabase version)
from supabase import create_client, ClientOptions
import time, streamlit as st

def client():
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"],
            options=ClientOptions(auto_refresh_token=False, persist_session=False))
    return st.session_state.sb

def login(email, pw):
    res = client().auth.sign_in_with_password({"email": email, "password": pw})
    st.session_state.user_id = res.user.id

def ensure_fresh():               # call at top of every run when logged in
    s = client().auth.get_session()
    if s is None:
        return logout()
    if s.expires_at - time.time() < 120:
        try:
            client().auth.refresh_session()
        except Exception:         # AuthApiError: refresh token revoked/used
            logout()

def logout():
    try:
        client().auth.sign_out({"scope": "local"})  # default "global" logs out ALL devices
    finally:
        st.session_state.clear(); st.rerun()
```
- Why `auto_refresh_token=False`: auto-refresh runs a background timer thread per client; manual refresh per rerun is deterministic and avoids double-use races of the single-use refresh token.
- **Persistence across reload:** `st.session_state` dies on full browser refresh/new tab. Streamlit can only *read* cookies natively (`st.context.cookies`, read-only, https://docs.streamlit.io/develop/api-reference/caching-and-state/st.context); writing needs a third-party component (not approved). Do **not** put tokens in `st.query_params` (URL history/sharing leak). For two users, re-login with the phone's password manager is acceptable.
  - Tip (verify): raise `server.disconnectedSessionTTL` in `.streamlit/config.toml` so a phone that sleeps/locks briefly reconnects to the same session instead of losing login. Check with `streamlit config show`.
- **Create the two users:** Supabase Dashboard > Authentication > Users > "Add user" > "Create new user", tick **Auto Confirm User**. Nick does this (team may not create accounts).
- **Disable signups: YES.** Authentication > Sign In / Providers > turn off "Allow new users to sign up" (API: `disable_signup`, https://supabase.com/docs/reference/api/v1-update-auth-service-config). Otherwise anyone with the key can call `auth.sign_up`. App must not have a sign-up UI.
- Password reset: out of scope for v1; Nick can reset from the dashboard.

## 2. Data security (RLS, no delete)

**Recommendation: membership table + `is_member()` helper; policies for SELECT/INSERT/UPDATE only, to `authenticated`; revoke DELETE/TRUNCATE; plus BEFORE DELETE and BEFORE TRUNCATE triggers.**

```sql
create table public.household_members (
  user_id uuid primary key references auth.users(id),
  name text not null check (name in ('nick','natalie')));
-- Nick inserts the 2 rows via SQL editor after creating users.
alter table public.household_members enable row level security;
create policy members_read on public.household_members
  for select to authenticated using ((select auth.uid()) = user_id or public.is_member());

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.household_members where user_id = (select auth.uid()));
$$;
revoke execute on function public.is_member() from anon, public;
grant execute on function public.is_member() to authenticated;

-- per data table (tasks, grocery_items):
alter table public.tasks enable row level security;
create policy tasks_select on public.tasks for select to authenticated using (public.is_member());
create policy tasks_insert on public.tasks for insert to authenticated
  with check (public.is_member() and created_by = (select auth.uid()));
create policy tasks_update on public.tasks for update to authenticated
  using (public.is_member()) with check (public.is_member());
-- no delete policy
revoke delete, truncate on public.tasks from anon, authenticated;
revoke all on public.tasks from anon;

create or replace function public.forbid_delete() returns trigger language plpgsql as $$
begin raise exception 'Deletes are not allowed; set archived_at instead'; end $$;
create trigger tasks_no_delete before delete on public.tasks
  for each row execute function public.forbid_delete();
create trigger tasks_no_truncate before truncate on public.tasks
  for each statement execute function public.forbid_delete();  -- row triggers don't fire on TRUNCATE
```
- Membership table (not just `using (true)`) = defense in depth if signups are ever re-enabled by accident.
- `(select auth.uid())` wrapping is Supabase's recommended RLS perf pattern.
- Trigger also blocks `service_role`/dashboard deletes (intended). Archived rows: filter `archived_at is null` in queries, not in RLS (so restore is possible).
- **Key in Streamlit secrets: publishable key (`sb_publishable_...`, or legacy `anon` key).** Never the secret/`service_role` key: it bypasses RLS, so a bug would expose/delete everything. Legacy anon/service_role keys are being deprecated "by end of 2026" (https://supabase.com/docs/guides/api/api-keys, https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys) -> **use the new publishable key now**; supabase-py accepts it as the 2nd `create_client` arg (official Python quickstart: https://supabase.com/docs/guides/getting-started/quickstarts/flask).
- Bonus: Streamlit runs server-side, so the key never reaches the browser.

## 3. Free tier and keep-alive

**Supabase Free** (https://supabase.com/pricing, https://supabase.com/docs/guides/platform/free-project-pausing): 500 MB DB, 1 GB file storage, 5 GB egress, 2 active projects, **no backups**. Paused after "too little user database activity over a 7-day period"; "a few user requests to the database each day" avoids it. Warning email ~1 week before. Paused projects restorable for 1 year. Caution: a restored project may lack legacy keys (another reason to use publishable key).

**Recommendation: one daily GitHub Actions workflow that does the backup (section 5); a real `pg_dump` is DB activity, so it doubles as the keep-alive.** Optionally add a cheap REST ping in the same job:
```yaml
- run: curl -fsS "$SUPABASE_URL/rest/v1/household_members?select=user_id&limit=1" -H "apikey: $SUPABASE_KEY"
```
(returns `[]` for anon under RLS, but still a DB query.) GitHub disables scheduled workflows after 60 days of no repo activity **in public repos only** (https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows); put it in a private repo (the daily backup commit also counts as activity).

**Streamlit Community Cloud sleep:** "All apps without traffic for 12 hours go to sleep" (https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app). Waking = open the app and click "Yes, get this app back up!" (~30-60 s). Plain HTTP GET pings do **not** keep it awake; only a headless browser does (Playwright/Selenium in GH Actions every ~6 h: https://dev.to/yasumorishima/http-200-but-your-streamlit-app-is-still-sleeping-why-get-requests-dont-work-and-how-playwright-3g67). Empty commits are unreliable. **Recommendation: accept the sleep for v1 (data is unaffected; only first morning load is slow).** Optional later: Playwright wake workflow (Playwright lives only in the workflow, not app deps). Only works for a public app.

## 4. Streamlit Community Cloud gotchas

- **Python:** default 3.12; choose in "Advanced settings" > Python version at deploy time (cannot change later without redeploying) (https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy). Pick 3.12 explicitly to match `.venv`.
- **Secrets:** paste TOML into Advanced settings > Secrets; read with `st.secrets["SUPABASE_URL"]`. Keep `.streamlit/secrets.toml` gitignored; commit only `secrets.toml.example`:
  ```toml
  SUPABASE_URL = "https://<ref>.supabase.co"
  SUPABASE_KEY = "sb_publishable_..."
  APP_TZ = "Europe/London"   # set to household's real zone
  ```
- **requirements.txt** at repo root (or next to entry file); pin versions (`streamlit==x.y.z`, `supabase==x.y.z`). Don't include pytest/ruff in it (put in `requirements-dev.txt`) to speed builds.
- **Private repo:** allowed, but "if your repo is private your app will be private", and "You are only allowed one private app at a time"; viewers must be invited and sign in to Streamlit (https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app). **Recommendation: public app repo** (no secrets in code; Supabase Auth + RLS is the security boundary; avoids double login on phones and allows a wake bot). Backups go to a separate **private** repo.
- Memory ~690 MB-2.7 GB; fine.
- **Mobile / home screen:** iOS Safari Share > "Add to Home Screen"; Android Chrome menu > "Add to Home screen". Use `st.set_page_config(layout="centered", page_title=..., page_icon=...)`, large buttons (`use_container_width=True`), avoid wide tables/many columns (`st.columns` stack on narrow screens). Collapse sidebar by default; put navigation in main area or `st.navigation(position="top")` (verify availability in pinned Streamlit version).

## 5. Backups

**Recommendation: daily GitHub Actions in a private repo using the official Supabase CLI recipe** (https://supabase.com/docs/guides/deployment/ci/backups):
```yaml
on: { schedule: [{cron: '17 3 * * *'}], workflow_dispatch: {} }
permissions: { contents: write }
jobs:
  dump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: supabase/setup-cli@v1
        with: { version: latest }
      - env: { DB_URL: "${{ secrets.SUPABASE_DB_URL }}" }
        run: |
          supabase db dump --db-url "$DB_URL" -f roles.sql --role-only
          supabase db dump --db-url "$DB_URL" -f schema.sql
          supabase db dump --db-url "$DB_URL" -f data.sql --use-copy --data-only
      - run: |
          git config user.name github-actions[bot]
          git config user.email 41898282+github-actions[bot]@users.noreply.github.com
          git add *.sql && (git diff --cached --quiet || git commit -m "backup $(date -u +%F)") && git push
```
- `SUPABASE_DB_URL` = **Session pooler** connection string (GitHub runners are IPv4-only; direct host is IPv6) - from Supabase "Connect" panel.
- Dumps include `auth.users` (emails, password hashes) -> repo **must be private**. Git history = point-in-time restore for free. Private-repo Actions minutes (2,000/mo free) easily cover ~1-2 min/day.
- Verify flag name (`--db-url` vs `--remote`) against current CLI docs when writing it.
- Also: soft-delete-only design means user mistakes are recoverable without backups.

## 6. Pitfalls

- **Timezones:** Streamlit Cloud servers run UTC. `date.today()` will be "tomorrow" in the evening for US / "yesterday" early morning in AU etc. Compute "today" as `datetime.now(ZoneInfo(st.secrets["APP_TZ"])).date()`; store timestamps as `timestamptz` (UTC), due dates as `date`.
- **Windows dev + zoneinfo:** Windows has no IANA tz database -> `ZoneInfoNotFoundError` locally unless the `tzdata` package is installed. Request PM approval to add `tzdata` (pure data, no code).
- **Python 3.12:** `datetime.utcnow()` is deprecated -> use `datetime.now(UTC)`. `datetime.fromisoformat` parses Supabase ISO strings with offsets (3.11+). Parse `due_date` with `date.fromisoformat`.
- **Recurrence:**
  - Monthly on 29-31: clamp to last day of month (Jan 31 -> Feb 28/29), and keep the original anchor day so Feb 28 -> Mar 31, not Mar 28 (store anchor or compute from series).
  - Decide: next due = previous due + interval (calendar chores) vs completion + interval. Recommend "previous due + interval, but if that's still in the past, roll forward until >= today" so overdue chores don't spawn a backlog.
  - No due date + recurrence: next due = today(APP_TZ) + interval.
  - **Double-submit:** Streamlit reruns/double taps can call `complete_task` twice -> two next occurrences. Make it idempotent: only spawn when the row transitions open->done (`update ... where id=? and status='open'` returning row; spawn only if a row came back). Better: a Postgres function (`security invoker`) doing both in one transaction, or a unique index on `(series_id, due_date)` (needs contract field, PM decision).
  - `reopen_task` after completion: don't spawn again on re-complete if the next occurrence already exists (same guard).
- **Streamlit:** every widget interaction reruns the whole script -> keep DB calls few; use `st.form` for add-task; key widgets by row id; never cache user-scoped data in `st.cache_data` without user id in the key (shared across sessions).
- **supabase-py errors:** wrap PostgREST calls; an expired/invalid JWT gives a 401/PGRST301 -> call `logout()` rather than crashing.
- `update_task(**fields)` must whitelist columns (never let `created_by`/`archived_at` be set from UI).

---

## Decisions for PM

1. Use the **publishable key** (`sb_publishable_...`) in `st.secrets`; never secret/service_role key in the app.
2. Per-session supabase client in `st.session_state` (never `cache_resource`); manual refresh per run; `sign_out(scope="local")`.
3. Accept re-login after full browser reload (no cookie dependency); optionally raise `server.disconnectedSessionTTL`.
4. Nick creates both users in dashboard (Auto Confirm), inserts `household_members` rows, then **disables signups**.
5. RLS via `household_members` + `is_member()`; no DELETE policy; revoke DELETE/TRUNCATE; BEFORE DELETE and BEFORE TRUNCATE triggers.
6. One daily GitHub Actions workflow in a **private backups repo**: `supabase db dump` + commit; doubles as Supabase keep-alive.
7. App repo **public** (Streamlit allows only one private app and forces viewer sign-in); accept 12 h sleep for v1.
8. Add `APP_TZ` secret and compute "today" in that zone; approve `tzdata` dependency for Windows dev.
9. Make `complete_task` idempotent (transition guard; ideally DB function or `series_id` + unique index - contract change?).
10. Select Python 3.12 in Streamlit Cloud Advanced settings; pin versions in `requirements.txt`, dev tools in `requirements-dev.txt`.
