# Daily backup + keep-alive (set up once, in a SEPARATE PRIVATE repo)

The dumps contain all your task and grocery data (public schema only; auth users,
emails and password hashes are deliberately NOT dumped), so this MUST live in a
private repo, never in the public app repo. After a restore, re-create the two
logins in the Supabase dashboard and re-run the household_members INSERT.

1. Create a new **private** GitHub repo, e.g. `home-app-backups`.
2. Copy `backup/.github/workflows/backup.yml` into it at the same path (`.github/workflows/backup.yml`) and push.
3. In Supabase click **Connect** and copy the **Session pooler** connection string
   (GitHub runners are IPv4-only; the direct connection is IPv6 and will fail). Put your DB password in it.
4. In the backups repo: Settings -> Secrets and variables -> Actions -> New repository secret:
   name `SUPABASE_DB_URL`, value the string from step 3.
5. Actions tab -> "Daily Supabase backup" -> Run workflow. Check it goes green and `schema.sql` and `data.sql` appear.
   If it fails on a flag name, check `supabase db dump --help` / Supabase's backup docs (flag spelling not yet verified against the current CLI).

Restore: into a fresh project run `schema.sql` then `data.sql` with `psql`, after the logins exist (see Supabase's restore docs).
Git history gives you a free daily snapshot. Not yet run against a real project.
