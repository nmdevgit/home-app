-- =====================================================================
-- NICK: paste this whole file into the Supabase dashboard
--   (Project -> SQL Editor -> New query) and press Run, by hand.
-- It is NOT run automatically by anything. Safe to run once on an empty
-- project; it will error (harmlessly) if re-run because tables exist.
--
-- AFTER running it (once Nick and Natalie exist under Authentication > Users),
-- run the two INSERTs in the "household_members" section near the bottom,
-- otherwise the app can read/write nothing. Then turn OFF "Allow new users
-- to sign up" (Authentication > Sign In / Providers).
--
-- Design rules:
--   * Only signed-in users listed in household_members can read/insert/update.
--   * There is NO delete policy AND a BEFORE DELETE trigger on every table,
--     so rows can never be deleted. "Removing" = set archived_at.
-- =====================================================================

create table public.profiles (
    id uuid primary key references auth.users (id),
    display_name text not null check (char_length(display_name) between 1 and 100),
    created_at timestamptz not null default now()
);

-- Allow-list of the two household users; defence in depth if sign-ups are
-- ever re-enabled by accident.
create table public.household_members (
    user_id uuid primary key references auth.users (id),
    name text not null check (name in ('nick', 'natalie'))
);

create table public.tasks (
    id uuid primary key default gen_random_uuid(),
    title text not null check (char_length(btrim(title)) between 1 and 200),
    notes text not null default '' check (char_length(notes) <= 2000),
    assignee text not null default 'either'
        check (assignee in ('nick', 'natalie', 'either')),
    due_date date,
    recurrence text not null default 'none'
        check (recurrence in ('none', 'daily', 'weekly', 'monthly')),
    status text not null default 'open' check (status in ('open', 'done')),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    archived_at timestamptz
);

create table public.grocery_items (
    id uuid primary key default gen_random_uuid(),
    name text not null check (char_length(btrim(name)) between 1 and 200),
    quantity text not null default '' check (char_length(quantity) <= 100),
    checked boolean not null default false,
    added_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

-- Indexes for the columns the app filters/sorts on.
create index tasks_status_idx on public.tasks (status) where archived_at is null;
create index tasks_due_date_idx on public.tasks (due_date);
create index tasks_assignee_idx on public.tasks (assignee);
create index grocery_active_idx on public.grocery_items (checked) where archived_at is null;

-- Hard-delete guard: fires even for the service role / SQL editor.
create or replace function public.forbid_delete() returns trigger
language plpgsql as $$
begin
    raise exception 'Deleting rows from % is not allowed; set archived_at instead', tg_table_name;
end;
$$;

create trigger household_members_no_delete before delete on public.household_members
    for each row execute function public.forbid_delete();
create trigger profiles_no_delete before delete on public.profiles
    for each row execute function public.forbid_delete();
create trigger tasks_no_delete before delete on public.tasks
    for each row execute function public.forbid_delete();
create trigger grocery_items_no_delete before delete on public.grocery_items
    for each row execute function public.forbid_delete();

create trigger profiles_no_truncate before truncate on public.profiles
    for each statement execute function public.forbid_delete();
create trigger tasks_no_truncate before truncate on public.tasks
    for each statement execute function public.forbid_delete();
create trigger grocery_items_no_truncate before truncate on public.grocery_items
    for each statement execute function public.forbid_delete();
create trigger household_members_no_truncate before truncate on public.household_members
    for each statement execute function public.forbid_delete();

-- Membership check used by every policy. SECURITY DEFINER so it can read
-- household_members without recursing through that table's own RLS.
create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = '' as $$
    select exists (
        select 1 from public.household_members where user_id = (select auth.uid())
    );
$$;
revoke execute on function public.is_member() from public, anon;
grant execute on function public.is_member() to authenticated;

-- Row Level Security. With RLS on and no policy for an operation,
-- that operation is denied; so DELETE is denied for everyone via the API.
alter table public.household_members enable row level security;
alter table public.profiles enable row level security;
alter table public.tasks enable row level security;
alter table public.grocery_items enable row level security;

-- Household app: any signed-in user (Nick or Natalie) sees everything.
-- (select auth.uid()) form lets Postgres cache the value per statement.
create policy members_select on public.household_members for select to authenticated
    using (user_id = (select auth.uid()) or public.is_member());

create policy profiles_select on public.profiles for select to authenticated
    using (public.is_member());
create policy profiles_insert on public.profiles for insert to authenticated
    with check (public.is_member() and id = (select auth.uid()));
create policy profiles_update on public.profiles for update to authenticated
    using (public.is_member() and id = (select auth.uid()))
    with check (public.is_member() and id = (select auth.uid()));

create policy tasks_select on public.tasks for select to authenticated
    using (public.is_member());
create policy tasks_insert on public.tasks for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
create policy tasks_update on public.tasks for update to authenticated
    using (public.is_member()) with check (public.is_member());

create policy grocery_select on public.grocery_items for select to authenticated
    using (public.is_member());
create policy grocery_insert on public.grocery_items for insert to authenticated
    with check (public.is_member() and added_by = (select auth.uid()));
create policy grocery_update on public.grocery_items for update to authenticated
    using (public.is_member()) with check (public.is_member());

-- Belt and braces: the anon role gets no table access at all, and nobody
-- gets DELETE/TRUNCATE through the API roles.
revoke all on public.household_members, public.profiles, public.tasks,
    public.grocery_items from anon;
revoke delete, truncate on public.household_members, public.profiles, public.tasks,
    public.grocery_items from authenticated;
grant select, insert on public.profiles, public.tasks, public.grocery_items
    to authenticated;
-- Column-level UPDATE: ownership columns (id, created_by, added_by, created_at)
-- can never be rewritten, so a row's author cannot be forged after the fact.
grant update (display_name) on public.profiles to authenticated;
grant update (title, notes, assignee, due_date, recurrence, status, completed_at, archived_at)
    on public.tasks to authenticated;
grant update (name, quantity, checked, archived_at) on public.grocery_items to authenticated;
grant select on public.household_members to authenticated;

-- ---------------------------------------------------------------------
-- household_members: Nick, run these by hand AFTER creating both users.
-- Replace the UUIDs with the ids shown in Authentication > Users.
-- ---------------------------------------------------------------------
-- insert into public.household_members (user_id, name) values
--     ('00000000-0000-0000-0000-000000000001', 'nick'),
--     ('00000000-0000-0000-0000-000000000002', 'natalie');
-- insert into public.profiles (id, display_name) values
--     ('00000000-0000-0000-0000-000000000001', 'Nick'),
--     ('00000000-0000-0000-0000-000000000002', 'Natalie');
