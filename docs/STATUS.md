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
