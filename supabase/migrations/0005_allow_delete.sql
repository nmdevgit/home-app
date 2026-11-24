-- =====================================================================
-- NICK: paste this whole file into the Supabase dashboard
--   (Project -> SQL Editor -> New query) and press Run, by hand,
--   AFTER 0001-0004 have been run. It is NOT run automatically.
-- Safe to re-run (drop-if-exists / create-or-replace). Touches no data.
--
-- Round 4: the app can now PERMANENTLY delete rows (this overrides the
-- "never delete" rule of 0001-0004). For tasks, subtasks, grocery_items,
-- meals, bills, notes, expenses and templates this:
--   1. drops the *_no_delete BEFORE DELETE triggers,
--   2. adds member-only DELETE policies (same is_member() pattern),
--   3. grants DELETE to authenticated (0001/0002 had revoked it).
-- TRUNCATE stays blocked (triggers kept, privilege stays revoked), and
-- profiles / household_members stay undeletable. anon still has no access.
-- subtasks.task_id now cascades, so deleting a task removes its subtasks.
-- =====================================================================

-- ---- 1. drop the delete guards (keep the truncate guards) ---------------
drop trigger if exists tasks_no_delete on public.tasks;
drop trigger if exists grocery_items_no_delete on public.grocery_items;
drop trigger if exists meals_no_delete on public.meals;
drop trigger if exists bills_no_delete on public.bills;
drop trigger if exists notes_no_delete on public.notes;
drop trigger if exists subtasks_no_delete on public.subtasks;
drop trigger if exists expenses_no_delete on public.expenses;
drop trigger if exists templates_no_delete on public.templates;

-- ---- 2. cascade subtasks when their task is deleted ---------------------
alter table public.subtasks drop constraint if exists subtasks_task_id_fkey;
alter table public.subtasks add constraint subtasks_task_id_fkey
    foreign key (task_id) references public.tasks (id) on delete cascade;

-- ---- 3. member-only DELETE policies --------------------------------------
drop policy if exists tasks_delete on public.tasks;
create policy tasks_delete on public.tasks for delete to authenticated
    using (public.is_member());
drop policy if exists grocery_delete on public.grocery_items;
create policy grocery_delete on public.grocery_items for delete to authenticated
    using (public.is_member());
drop policy if exists meals_delete on public.meals;
create policy meals_delete on public.meals for delete to authenticated
    using (public.is_member());
drop policy if exists bills_delete on public.bills;
create policy bills_delete on public.bills for delete to authenticated
    using (public.is_member());
drop policy if exists notes_delete on public.notes;
create policy notes_delete on public.notes for delete to authenticated
    using (public.is_member());
drop policy if exists subtasks_delete on public.subtasks;
create policy subtasks_delete on public.subtasks for delete to authenticated
    using (public.is_member());
drop policy if exists expenses_delete on public.expenses;
create policy expenses_delete on public.expenses for delete to authenticated
    using (public.is_member());
drop policy if exists templates_delete on public.templates;
create policy templates_delete on public.templates for delete to authenticated
    using (public.is_member());

-- ---- 4. grants ---------------------------------------------------------------
-- 0001/0002 revoked DELETE; 0004 revoked ALL on the new tables. Grant it back
-- (and only DELETE: truncate stays revoked).
grant delete on public.tasks, public.grocery_items, public.meals, public.bills,
    public.notes, public.subtasks, public.expenses, public.templates to authenticated;
revoke truncate on public.tasks, public.grocery_items, public.meals, public.bills,
    public.notes, public.subtasks, public.expenses, public.templates from authenticated;
