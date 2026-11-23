# Home App - PM Status / Resume Point

If a session ends or tokens run out: read this file, then continue from "Next up".
PM (main Claude session) approves agent requests while the user (Nick) is away.

## Decisions (locked)
- Streamlit app, deployed free on Streamlit Community Cloud from GitHub. Python 3.12, venv at `.venv`.
- Data: Supabase (free Postgres + Supabase Auth). Two users with separate logins: Nick, Natalie.
- No data deletion: soft-delete only (`archived_at`); DB blocks DELETE (RLS has no delete policy + trigger). Stay within free tier (500 MB).
- Dev/tests use a SQLite repo implementing the same `Repository` protocol (`core/repo.py`).
- Computer off must not affect the service (everything runs in the cloud).
- Features v1: tasks/chores (assignee, due date, recurrence), grocery list, today dashboard.
- Allowed deps (PM-approved): streamlit, supabase, pytest, ruff. Anything else: ask PM.
- NOT allowed without Nick: creating accounts, pushing to GitHub, touching real Supabase, commits.

## Roles / ownership
- Researcher (opus): read-only; writes `docs/research.md` only.
- Backend (sonnet): `core/` (except repo.py), `supabase/`, `tests/`, `requirements.txt`.
- Frontend (sonnet): `app.py`, `views/`, `.streamlit/config.toml`, `.streamlit/secrets.toml.example`.
- Contract `core/repo.py` is PM-owned; request changes via PM.

## Progress
- [x] venv (.venv, Python 3.12.9), contract, plan
- [ ] Research (auth approach, RLS, keep-alive vs 7-day pause, Streamlit Cloud gotchas)
- [ ] Backend: SQLite repo + tests, Supabase repo, migration SQL, auth module
- [ ] Frontend: login, tasks, grocery, dashboard
- [ ] PM review, ruff/pytest green
- [ ] Deploy guide for Nick (GitHub + Supabase + Streamlit Cloud steps)

## DEPLOYED 2026-11-23
Supabase project + both users + household_members/profiles rows done; sign-ups off. GitHub repo nmdevgit/home-app (public, pushed). Streamlit Cloud app deployed; Nick and Natalie logins both confirmed working; Tasks page defaults to All (pushed). Pending: phone home-screen shortcuts, backup repo (backup/README.md) - SKIPPED by Nick, don't push it unless asked (local folder C:\Users\nickm\home-app-backups is unused and can be deleted). Consequence: open the app weekly or Supabase free pauses after 7 days; no backups exist.
Lessons: SUPABASE_URL must start with https://; placeholder secret values give a generic "sign-in failed". TODO: show a clear config error for a bad URL/key instead of a raw exception.

## ROUND 1+2 (started 2026-11-23, approved by Nick)
Scope: search+priority on tasks; grocery categories/frequent items/edit; Archive (restore) screen + "Done this week" history; storage meter (Settings page); meal planner -> grocery; bills tracker (monthly total); shared notes; chore rotation. Contract extended in core/repo.py (PM-owned). Backend: core/ + supabase/migrations/0002_round2.sql (+tests). Frontend: views/, ui/, app.py. Text only, every list has a limit, nothing cached across users. 0002 SQL must be pasted into Supabase by Nick before the new pages work. No push until Nick says so. Round 3 (stats, calendar view, email reminders) NOT approved yet.
If a session dies: check which files exist/tests pass, respawn missing role from this description.

## ROUND 3 (started 2026-11-23, approved "go" by Nick): UI redesign + more features
Round 1+2 pushed & live; 0002 run in Supabase; 0003 (column grants fix) written, Nick running it. Round 3 scope: modern UI (theme/cards/badges/person colours, redesigned Today/Tasks/Grocery, mobile-first) + agenda view, stats (chores per person), quick-add parser (local, no AI), CSV export in Settings, shared expenses (who owes whom), templates (shopping lists + recipes), subtasks, Task.completed_by. Contract extended in core/repo.py. Backend: core/ + supabase/migrations/0004_round3.sql (LESSON: Supabase default-grants table-wide UPDATE; new tables MUST `revoke update ... from authenticated` before column-level grants) + core/quickadd.py, core/stats.py, rules.expense_balance_cents. Frontend: ui/theme.py, views/, app.py, .streamlit/config.toml. No push until Nick says. Email reminders NOT approved.

## Next up
v1 code COMPLETE and PM-reviewed (60 pytest pass, ruff clean, SQL reviewed, no secrets in repo). docs/DEPLOY.md written.
Waiting on Nick (back tomorrow): decide public/private repo, give APP_TZ, then do the account steps in docs/DEPLOY.md; first real-Supabase test is still outstanding.
DECIDED by Nick 2026-11-23: APP_TZ=Australia/Sydney; app repo PUBLIC (final; supersedes private); backups in a separate PRIVATE repo; login emails are given to Streamlit secrets (NICK_EMAIL/NATALIE_EMAIL) only; NEVER write them in repo files (repo is public).
PARKED by Nick (do not build unless he asks again): Gmail read/summarize/draft-reply feature (needs Claude API key = small cost, Google OAuth; draft-only recommended).
Optional next work (not started): GitHub Action for daily backup + keep-alive (see docs/research.md), git init + first commit, restore-archived UI, dashboard polish.

## Log
- 2026-11-23 PM: researcher DONE (docs/research.md). tzdata approved+installed. Sent decisions to backend (RLS/household_members, idempotent complete, APP_TZ clock, auth per-session) and frontend (session_state client, secrets names SUPABASE_URL/SUPABASE_KEY/APP_TZ). Open for Nick: public vs private GitHub repo (research recommends public app repo + separate private repo for daily backup/keep-alive job); Streamlit app sleeps after 12h idle (accepted for v1).
- 2026-11-23 PM: venv (3.12.9) created; deps installed (streamlit, supabase, pytest, ruff); contract core/repo.py written; 3 agents spawned.
- 2026-11-23 backend: core/{errors,rules,clock,sqlite_repo,supabase_repo,auth}.py, supabase/migrations/0001_init.sql (household_members+is_member RLS, no delete/truncate), tests (49 pass), pyproject ruff cfg. Pending: pin streamlit/supabase in requirements.txt (not installed in venv).
- 2026-11-23 frontend: app.py, views/{login,dashboard,tasks,grocery}.py, ui/, .streamlit config+secrets example done; dev mode (HOME_APP_DEV=1) boots, 8 UI tests pass, ruff clean. Cloud path untested (no Supabase).
- 2026-11-23 frontend: today via core.clock+APP_TZ (st.error on invalid); email->person only via NICK_EMAIL/NATALIE_EMAIL, unmatched account is signed out with message.
- 2026-11-23 backend: pinned deps; verified auth vs supabase 2.34.1; recurrence rolls forward to first occurrence >= today (APP_TZ). Archived-row restore is manual in the Supabase dashboard (set archived_at = null); no app/repo restore in v1.
- 2026-11-23 frontend round 2: views/{archive,meals,bills,notes,settings}.py new; tasks (search/priority/rotate), grocery (categories/frequent/edit), dashboard (bills+meals) updated; ui/money.py, grouping helpers; app.py nav grouped (Today/Tasks/Grocery, Plan, More). Tests: tests/test_ui_pages.py (fake repo), test_ui_pages_sqlite.py; 85 pass, ruff clean, dev boot on :8599 returns 200. Cloud path untested; needs 0002 SQL applied.
- 2026-11-23 backend: round 2 DONE in both repos (SqliteRepository + SupabaseRepository): task priority/rotate/limit/done/archived+restore, grocery category/update/archived/restore/frequent, meals (+meal_to_grocery), bills (+mark_bill_paid advance), notes, storage_usage; rules.monthly_equivalent_cents/next_bill_due/clamp_limit; supabase/migrations/0002_round2.sql written (NOT run; Nick pastes it after 0001); tests added, 127 pytest pass, ruff clean.
- 2026-11-23 backend round 3 DONE (both repos): Task.completed_by, subtasks, expenses, templates, list_members, export_rows (paged 1000/req on Supabase); rules.expense_balance_cents, core/stats.py, core/quickadd.py; supabase/migrations/0004_round3.sql written (NOT run; Nick pastes after 0001-0003, and BEFORE deploying code, since task selects now include completed_by). Tests tests/test_round3_{sqlite,supabase,logic}.py; ruff clean.
- 2026-11-23 frontend round 3: ui/{theme,taskui,export}.py (scoped CSS, cards, badges, avatars, hero), config.toml light/dark theme; Today/Tasks/Grocery redesigned (quick-add preview, schedule groups, subtasks, aisles, saved lists); new views agenda/stats/expenses/templates; Settings 'Download my data' zip; nav Today/Tasks/Grocery | Plan | Lists | More; tests/test_ui_round3.py (36 tests). Dev boot :8599 200. Ruff clean for frontend files.
