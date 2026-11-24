-- =====================================================================
-- NICK: paste this whole file into the Supabase dashboard
--   (Project -> SQL Editor -> New query) and press Run, by hand,
--   AFTER 0001-0005 have been run. It is NOT run automatically.
-- Safe to re-run: tables/indexes use IF NOT EXISTS; policies, triggers and
-- constraints are dropped and recreated. Touches no existing data.
--
-- Round 4 adds:
--   user_prefs  per-PERSON look-and-feel (accent, pinned shortcuts, start page).
--               RLS is on auth.uid(): Nick cannot read or write Natalie's row.
--   events      shared calendar entries / countdowns (household RLS).
--   goals       savings goals (household RLS).
--   goal_moves  deposits / withdrawals for a goal; deleted with the goal (cascade).
--
-- Same pattern as 0004/0005: members only; REVOKE the Supabase default grants
-- first, then grant back select/insert/delete and UPDATE on editable columns
-- only (id, created_by, created_at are never updatable); TRUNCATE is blocked.
-- Deleting is allowed (0005 policy): there is a member-only delete policy.
-- =====================================================================

-- ---- tables ----------------------------------------------------------------
create table if not exists public.user_prefs (
    user_id uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    accent text not null default 'teal'
        check (accent in ('teal', 'indigo', 'rose', 'amber', 'violet')),
    pinned text not null default '' check (char_length(pinned) <= 200),
    start_page text not null default 'today' check (char_length(start_page) between 1 and 40),
    compact boolean not null default false,
    updated_at timestamptz not null default now()
);

create table if not exists public.events (
    id uuid primary key default gen_random_uuid(),
    title text not null check (char_length(btrim(title)) between 1 and 120),
    day date not null,
    start_time time,
    who text not null default 'both' check (who in ('nick', 'natalie', 'both')),
    notes text not null default '' check (char_length(notes) <= 1000),
    recurrence text not null default 'none'
        check (recurrence in ('none', 'weekly', 'monthly', 'yearly')),
    remind_days integer not null default 0 check (remind_days between 0 and 60),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.goals (
    id uuid primary key default gen_random_uuid(),
    name text not null check (char_length(btrim(name)) between 1 and 80),
    target_cents bigint not null check (target_cents between 1 and 1000000000),
    due_date date,
    icon text not null default 'savings'
        check (icon in ('savings', 'holiday', 'home', 'car', 'gift', 'wedding', 'tech', 'other')),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.goal_moves (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references public.goals (id) on delete cascade,
    amount_cents bigint not null
        check (amount_cents between -1000000000 and 1000000000 and amount_cents <> 0),
    person text not null check (person in ('nick', 'natalie')),
    day date not null,
    note text not null default '' check (char_length(note) <= 120),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now()
);

-- ---- indexes -----------------------------------------------------------------
create index if not exists events_day_idx on public.events (day) where archived_at is null;
create index if not exists goals_created_idx on public.goals (created_at) where archived_at is null;
create index if not exists goal_moves_goal_idx on public.goal_moves (goal_id, created_at desc);

-- ---- user_prefs.updated_at is maintained by the database (0002 function) ---------
drop trigger if exists user_prefs_touch_updated_at on public.user_prefs;
create trigger user_prefs_touch_updated_at before update on public.user_prefs
    for each row execute function public.touch_updated_at();

-- ---- no truncate (delete is allowed, see 0005) -----------------------------------
drop trigger if exists events_no_truncate on public.events;
create trigger events_no_truncate before truncate on public.events
    for each statement execute function public.forbid_delete();
drop trigger if exists goals_no_truncate on public.goals;
create trigger goals_no_truncate before truncate on public.goals
    for each statement execute function public.forbid_delete();
drop trigger if exists goal_moves_no_truncate on public.goal_moves;
create trigger goal_moves_no_truncate before truncate on public.goal_moves
    for each statement execute function public.forbid_delete();
drop trigger if exists user_prefs_no_truncate on public.user_prefs;
create trigger user_prefs_no_truncate before truncate on public.user_prefs
    for each statement execute function public.forbid_delete();

-- ---- row level security ---------------------------------------------------------------
-- user_prefs: PER PERSON (auth.uid()), not household. No delete policy.
alter table public.user_prefs enable row level security;
drop policy if exists user_prefs_select on public.user_prefs;
create policy user_prefs_select on public.user_prefs for select to authenticated
    using (public.is_member() and user_id = (select auth.uid()));
drop policy if exists user_prefs_insert on public.user_prefs;
create policy user_prefs_insert on public.user_prefs for insert to authenticated
    with check (public.is_member() and user_id = (select auth.uid()));
drop policy if exists user_prefs_update on public.user_prefs;
create policy user_prefs_update on public.user_prefs for update to authenticated
    using (public.is_member() and user_id = (select auth.uid()))
    with check (public.is_member() and user_id = (select auth.uid()));

-- events / goals / goal_moves: household members, with delete.
alter table public.events enable row level security;
drop policy if exists events_select on public.events;
create policy events_select on public.events for select to authenticated
    using (public.is_member());
drop policy if exists events_insert on public.events;
create policy events_insert on public.events for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists events_update on public.events;
create policy events_update on public.events for update to authenticated
    using (public.is_member()) with check (public.is_member());
drop policy if exists events_delete on public.events;
create policy events_delete on public.events for delete to authenticated
    using (public.is_member());

alter table public.goals enable row level security;
drop policy if exists goals_select on public.goals;
create policy goals_select on public.goals for select to authenticated
    using (public.is_member());
drop policy if exists goals_insert on public.goals;
create policy goals_insert on public.goals for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists goals_update on public.goals;
create policy goals_update on public.goals for update to authenticated
    using (public.is_member()) with check (public.is_member());
drop policy if exists goals_delete on public.goals;
create policy goals_delete on public.goals for delete to authenticated
    using (public.is_member());

alter table public.goal_moves enable row level security;
drop policy if exists goal_moves_select on public.goal_moves;
create policy goal_moves_select on public.goal_moves for select to authenticated
    using (public.is_member());
drop policy if exists goal_moves_insert on public.goal_moves;
create policy goal_moves_insert on public.goal_moves for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists goal_moves_delete on public.goal_moves;
create policy goal_moves_delete on public.goal_moves for delete to authenticated
    using (public.is_member());
-- goal_moves has no update policy and no update grant: a wrong entry is deleted and re-added.

-- ---- grants (revoke the Supabase defaults first, then add back) ----------------------
revoke all on public.user_prefs from anon;
revoke all on public.user_prefs from authenticated;
grant select, insert on public.user_prefs to authenticated;
grant update (accent, pinned, start_page, compact) on public.user_prefs to authenticated;

revoke all on public.events from anon;
revoke all on public.events from authenticated;
grant select, insert, delete on public.events to authenticated;
grant update (title, day, start_time, who, notes, recurrence, remind_days, archived_at)
    on public.events to authenticated;

revoke all on public.goals from anon;
revoke all on public.goals from authenticated;
grant select, insert, delete on public.goals to authenticated;
grant update (name, target_cents, due_date, icon, archived_at) on public.goals to authenticated;

revoke all on public.goal_moves from anon;
revoke all on public.goal_moves from authenticated;
grant select, insert, delete on public.goal_moves to authenticated;
