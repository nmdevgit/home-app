# Deploy guide (all free)

Do these in order. Nothing here has been done yet; the app has only been run locally in dev mode.
Supabase/Streamlit menu names change occasionally; if a label differs, look for the closest one.

## 0. Try it locally first (no accounts needed)
```
$env:HOME_APP_DEV = "1"; .\.venv\Scripts\python.exe -m streamlit run app.py
```
Dev mode needs that explicit `HOME_APP_DEV=1` (banner shown, Nick/Natalie picker, data in `dev_home.db`, no real login).
Without it, missing secrets make the app show a configuration error and stop (fail closed). Never set HOME_APP_DEV on Streamlit Cloud.

## 1. Supabase (database + logins)
1. Sign up at supabase.com, create a new project (free plan). Pick a region near you, save the DB password.
2. SQL Editor -> New query -> paste all of `supabase/migrations/0001_init.sql` -> Run.
3. Authentication -> Users -> Add user, twice (Nick, Natalie): email + password, tick **Auto Confirm User**.
4. Copy each user's UUID (Authentication -> Users). In the SQL Editor run the two commented INSERTs at the bottom of `0001_init.sql` with the real UUIDs (uncomment them). Until you do, the app can read/write nothing.
5. Authentication -> Sign In / Providers: turn **off** "Allow new users to sign up".
6. Project Settings -> API: copy the Project URL and the **publishable** key (`sb_publishable_...`).
   Never use the secret / service_role key in this app.

## 2. GitHub
1. Create a repo and push this folder (the `.gitignore` already excludes `.venv`, `*.db`, and `.streamlit/secrets.toml`).
2. DECIDED: **public app repo**. No secrets live in the code (they go in Streamlit's settings), so Nick and Natalie can open the app URL without a GitHub account; only the app's Supabase login applies.
   Do not put keys, emails or data in the repo. Backups go in a separate **private** repo (see `backup/README.md`).

## 3. Streamlit Community Cloud
1. share.streamlit.io -> sign in with GitHub -> Create app -> pick the repo, branch `main`, main file `app.py`.
2. Advanced settings: **Python 3.12**; paste secrets (see `.streamlit/secrets.toml.example`):
   ```
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "sb_publishable_..."
   APP_TZ = "Australia/Sydney"
   NICK_EMAIL = "..."
   NATALIE_EMAIL = "..."
   ```
3. Deploy. On each phone: open the URL, log in, then Add to Home Screen.

## 4. Known limits / follow-ups
- The app sleeps after ~12h with no visitors; opening it wakes it (a few seconds).
- Supabase free projects pause after ~7 days of low activity. Open the app at least weekly, or add the daily keep-alive/backup GitHub Action described in `docs/research.md` (not built yet).
- No backups on Supabase free: set up the daily export from `docs/research.md` (not built yet).
- Data is never deleted by the app. To restore an archived row: set `archived_at` to null in the Supabase table editor. Deleting is blocked by a database trigger on purpose (drop the trigger in SQL if you ever must).
- After a full browser reload you log in again.
- Not yet tested against a real Supabase project: do a first run with both accounts and report anything odd.
