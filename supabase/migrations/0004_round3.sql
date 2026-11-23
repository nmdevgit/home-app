-- =====================================================================
-- NICK: paste this whole file into the Supabase dashboard
--   (Project -> SQL Editor -> New query) and press Run, by hand,
--   AFTER 0001, 0002 and 0003 have been run. It is NOT run automatically.
-- Safe to re-run: columns/tables/indexes use IF NOT EXISTS; policies,
-- triggers and constraints are dropped and recreated. Touches no data.
--
-- Adds: tasks.completed_by, and new tables subtasks, expenses, templates.
-- Same rules as 0001-0003: members only, no delete policy, delete/truncate
-- triggers, anon has no access.
--
-- LESSON (see 0003): Supabase default-grants table-wide privileges to
-- `authenticated`, and a column-level GRANT only ADDS to them. So for every
-- NEW table we first REVOKE ALL from authenticated and then grant back only
-- select, insert and UPDATE on the editable columns. Ownership columns
-- (id, created_by, created_at) are never updatable by the app.
--
-- completed_by integrity: a BEFORE INSERT/UPDATE trigger on tasks rejects a
-- completed_by that is neither NULL, unchanged, nor the caller's own
-- auth.uid() -- so Nick cannot mark a chore as "done by Natalie". It is
-- skipped when auth.uid() is NULL (SQL editor / admin work).
-- =====================================================================

-- ---- tasks.completed_by ----------------------------------------------
alter table public.tasks
    add column if not exists completed_by uuid references auth.users (id);

create or replace function public.check_completed_by() returns trigger
language plpgsql as $$
begin
    if new.completed_by is not null
       and (select auth.uid()) is not null
       and new.completed_by is distinct from (select auth.uid())
       and (tg_op = 'INSERT' or new.completed_by is distinct from old.completed_by) then
        raise exception 'completed_by can only be set to yourself';
    end if;
    return new;
end;
$$;
drop trigger if exists tasks_check_completed_by on public.tasks;
create trigger tasks_check_completed_by before insert or update on public.tasks
    for each row execute function public.check_completed_by();

-- 0003 already revoked table-wide UPDATE on tasks; just add the new column.
grant update (completed_by) on public.tasks to authenticated;

-- ---- new tables --------------------------------------------------------
create table if not exists public.subtasks (
    id uuid primary key default gen_random_uuid(),
    task_id uuid not null references public.tasks (id),
    title text not null check (char_length(btrim(title)) between 1 and 200),
    done boolean not null default false,
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.expenses (
    id uuid primary key default gen_random_uuid(),
    day date not null,
    description text not null check (char_length(btrim(description)) between 1 and 200),
    amount_cents bigint not null check (amount_cents between 1 and 100000000),
    paid_by text not null check (paid_by in ('nick', 'natalie')),
    split text not null default 'equal' check (split in ('equal', 'payer_only', 'other_only')),
    kind text not null default 'expense' check (kind in ('expense', 'settlement')),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.templates (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('shopping', 'recipe')),
    name text not null check (char_length(btrim(name)) between 1 and 100),
    items text not null default ''
        check (char_length(items) <= 2000
               and cardinality(regexp_split_to_array(items, E'\n')) <= 60
               and items !~ E'[^\n]{201}'),
    created_by uuid not null default auth.uid() references auth.users (id),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

-- ---- indexes -----------------------------------------------------------
create index if not exists subtasks_task_idx on public.subtasks (task_id)
    where archived_at is null;
create index if not exists expenses_day_idx on public.expenses (day desc, created_at desc)
    where archived_at is null;
create index if not exists templates_kind_idx on public.templates (kind, name)
    where archived_at is null;
create index if not exists tasks_completed_by_idx on public.tasks (completed_by, completed_at);

-- ---- no deletes ----------------------------------------------------------
drop trigger if exists subtasks_no_delete on public.subtasks;
create trigger subtasks_no_delete before delete on public.subtasks
    for each row execute function public.forbid_delete();
drop trigger if exists subtasks_no_truncate on public.subtasks;
create trigger subtasks_no_truncate before truncate on public.subtasks
    for each statement execute function public.forbid_delete();
drop trigger if exists expenses_no_delete on public.expenses;
create trigger expenses_no_delete before delete on public.expenses
    for each row execute function public.forbid_delete();
drop trigger if exists expenses_no_truncate on public.expenses;
create trigger expenses_no_truncate before truncate on public.expenses
    for each statement execute function public.forbid_delete();
drop trigger if exists templates_no_delete on public.templates;
create trigger templates_no_delete before delete on public.templates
    for each row execute function public.forbid_delete();
drop trigger if exists templates_no_truncate on public.templates;
create trigger templates_no_truncate before truncate on public.templates
    for each statement execute function public.forbid_delete();

-- ---- row level security (no delete policy => delete denied) -----------
alter table public.subtasks enable row level security;
drop policy if exists subtasks_select on public.subtasks;
create policy subtasks_select on public.subtasks for select to authenticated
    using (public.is_member());
drop policy if exists subtasks_insert on public.subtasks;
create policy subtasks_insert on public.subtasks for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists subtasks_update on public.subtasks;
create policy subtasks_update on public.subtasks for update to authenticated
    using (public.is_member()) with check (public.is_member());
alter table public.expenses enable row level security;
drop policy if exists expenses_select on public.expenses;
create policy expenses_select on public.expenses for select to authenticated
    using (public.is_member());
drop policy if exists expenses_insert on public.expenses;
create policy expenses_insert on public.expenses for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists expenses_update on public.expenses;
create policy expenses_update on public.expenses for update to authenticated
    using (public.is_member()) with check (public.is_member());
alter table public.templates enable row level security;
drop policy if exists templates_select on public.templates;
create policy templates_select on public.templates for select to authenticated
    using (public.is_member());
drop policy if exists templates_insert on public.templates;
create policy templates_insert on public.templates for insert to authenticated
    with check (public.is_member() and created_by = (select auth.uid()));
drop policy if exists templates_update on public.templates;
create policy templates_update on public.templates for update to authenticated
    using (public.is_member()) with check (public.is_member());

-- ---- grants (revoke the Supabase defaults first, then add back) --------
revoke all on public.subtasks from anon;
revoke all on public.subtasks from authenticated;
grant select, insert on public.subtasks to authenticated;
grant update (title, done, archived_at) on public.subtasks to authenticated;
revoke all on public.expenses from anon;
revoke all on public.expenses from authenticated;
grant select, insert on public.expenses to authenticated;
grant update (archived_at) on public.expenses to authenticated;
revoke all on public.templates from anon;
revoke all on public.templates from authenticated;
grant select, insert on public.templates to authenticated;
grant update (name, items, archived_at) on public.templates to authenticated;
