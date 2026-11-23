-- =====================================================================
-- NICK: paste this whole file into the Supabase dashboard
--   (Project -> SQL Editor -> New query) and press Run, by hand,
--   AFTER 0001_init.sql has been run. It is NOT run automatically.
-- Safe to re-run: columns/tables/indexes use IF NOT EXISTS, policies and
-- triggers are dropped and recreated.
--
-- Adds: tasks.priority/rotate, grocery_items.category, and new tables
-- meals, bills, notes, plus public.db_size() for the storage meter.
-- Same rules as 0001: members only, no delete policy, delete/truncate
-- triggers, anon has no access, ownership columns are never updatable.
-- =====================================================================

-- ---- existing tables: new columns -----------------------------------
alter table public.tasks
    add column if not exists priority text not null default 'normal',
    add column if not exists rotate boolean not null default false;
alter table public.tasks drop constraint if exists tasks_priority_check;
alter table public.tasks add constraint tasks_priority_check
    check (priority in ('high', 'normal', 'low'));

alter table public.grocery_items
    add column if not exists category text not null default 'other';
alter table public.grocery_items drop constraint if exists grocery_items_category_check;
alter table public.grocery_items add constraint grocery_items_category_check
    check (category in ('produce', 'dairy', 'meat', 'bakery', 'pantry', 'frozen',
                        'drinks', 'household', 'other'));

-- ---- new tables ------------------------------------------------------
create table if not exists public.meals (
    id uuid primary key default gen_random_uuid(),
    day date not null,
    slot text not null default 'dinner' check (slot in ('breakfast', 'lunch', 'dinner')),
    title text not null check (char_length(btrim(title)) between 1 and 200),
    ingredients text not null default ''
        check (char_length(ingredients) <= 2000
               and cardinality(regexp_split_to_array(ingredients, E'\n')) <= 40),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.bills (
    id uuid primary key default gen_random_uuid(),
    name text not null check (char_length(btrim(name)) between 1 and 200),
    amount_cents bigint not null check (amount_cents between 0 and 100000000),
    due_date date not null,
    recurrence text not null default 'monthly'
        check (recurrence in ('none', 'weekly', 'fortnightly', 'monthly', 'yearly')),
    last_paid_on date,
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.notes (
    id uuid primary key default gen_random_uuid(),
    title text not null check (char_length(btrim(title)) between 1 and 200),
    body text not null default '' check (char_length(body) <= 5000),
    pinned boolean not null default false,
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    archived_at timestamptz
);

-- notes.updated_at is maintained by the database, not trusted from the client.
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;
drop trigger if exists notes_touch_updated_at on public.notes;
create trigger notes_touch_updated_at before update on public.notes
    for each row execute function public.touch_updated_at();

-- ---- indexes ---------------------------------------------------------
create index if not exists meals_day_idx on public.meals (day) where archived_at is null;
create index if not exists bills_due_date_idx on public.bills (due_date) where archived_at is null;
create index if not exists notes_order_idx
    on public.notes (pinned desc, updated_at desc) where archived_at is null;
create index if not exists tasks_completed_at_idx on public.tasks (completed_at);

-- ---- no deletes ------------------------------------------------------
drop trigger if exists meals_no_delete on public.meals;
create trigger meals_no_delete before delete on public.meals
    for each row execute function public.forbid_delete();
drop trigger if exists bills_no_delete on public.bills;
create trigger bills_no_delete before delete on public.bills
    for each row execute function public.forbid_delete();
drop trigger if exists notes_no_delete on public.notes;
create trigger notes_no_delete before delete on public.notes
    for each row execute function public.forbid_delete();

drop trigger if exists meals_no_truncate on public.meals;
create trigger meals_no_truncate before truncate on public.meals
    for each statement execute function public.forbid_delete();
drop trigger if exists bills_no_truncate on public.bills;
create trigger bills_no_truncate before truncate on public.bills
    for each statement execute function public.forbid_delete();
drop trigger if exists notes_no_truncate on public.notes;
create trigger notes_no_truncate before truncate on public.notes
    for each statement execute function public.forbid_delete();

-- ---- row level security (no delete policy => delete denied) ----------
alter table public.meals enable row level security;
alter table public.bills enable row level security;
alter table public.notes enable row level security;

drop policy if exists meals_select on public.meals;
create policy meals_select on public.meals for select to authenticated
    using (public.is_member());
drop policy if exists meals_insert on public.meals;
create policy meals_insert on public.meals for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists meals_update on public.meals;
create policy meals_update on public.meals for update to authenticated
    using (public.is_member()) with check (public.is_member());

drop policy if exists bills_select on public.bills;
create policy bills_select on public.bills for select to authenticated
    using (public.is_member());
drop policy if exists bills_insert on public.bills;
create policy bills_insert on public.bills for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists bills_update on public.bills;
create policy bills_update on public.bills for update to authenticated
    using (public.is_member()) with check (public.is_member());

drop policy if exists notes_select on public.notes;
create policy notes_select on public.notes for select to authenticated
    using (public.is_member());
drop policy if exists notes_insert on public.notes;
create policy notes_insert on public.notes for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists notes_update on public.notes;
create policy notes_update on public.notes for update to authenticated
    using (public.is_member()) with check (public.is_member());

-- ---- grants ----------------------------------------------------------
revoke all on public.meals, public.bills, public.notes from anon;
revoke delete, truncate on public.meals, public.bills, public.notes from authenticated;
grant select, insert on public.meals, public.bills, public.notes to authenticated;

-- Column-level UPDATE: ownership columns (id, created_by, created_at) and
-- notes.updated_at (trigger-managed) are never updatable by the app.
grant update (day, slot, title, ingredients, archived_at) on public.meals to authenticated;
grant update (name, amount_cents, due_date, recurrence, last_paid_on, archived_at)
    on public.bills to authenticated;
grant update (title, body, pinned, archived_at) on public.notes to authenticated;
-- Extend the 0001 grants with the new columns (grants are additive).
grant update (priority, rotate) on public.tasks to authenticated;
grant update (category) on public.grocery_items to authenticated;

-- ---- storage meter ---------------------------------------------------
-- Total database size in bytes; only household members may read it.
create or replace function public.db_size() returns bigint
language plpgsql stable security definer set search_path = '' as $$
begin
    if not public.is_member() then
        raise exception 'not allowed';
    end if;
    return pg_database_size(current_database());
end;
$$;
revoke execute on function public.db_size() from public, anon;
grant execute on function public.db_size() to authenticated;
