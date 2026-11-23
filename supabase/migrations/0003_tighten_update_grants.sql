-- =====================================================================
-- NICK: paste into Supabase SQL Editor and Run, by hand, AFTER 0001 and 0002.
-- Safe to re-run. Does not touch any data.
--
-- Why: Supabase gives new tables a table-wide UPDATE privilege by default,
-- and a column-level GRANT only ADDS to it. So the "ownership columns can
-- never be edited" rule in 0001/0002 was not actually enforced. This removes
-- the table-wide UPDATE and re-grants UPDATE on the editable columns only.
-- Ownership columns (id, created_by/added_by, created_at, notes.updated_at)
-- become non-updatable for the app. (The notes.updated_at trigger still works.)
-- =====================================================================

revoke update on public.profiles, public.tasks, public.grocery_items,
    public.meals, public.bills, public.notes from authenticated;
-- household_members is read-only for the app (it has no write policies anyway).
revoke insert, update on public.household_members from authenticated;

grant update (display_name) on public.profiles to authenticated;
grant update (title, notes, assignee, due_date, recurrence, status, completed_at,
              archived_at, priority, rotate) on public.tasks to authenticated;
grant update (name, quantity, checked, archived_at, category)
    on public.grocery_items to authenticated;
grant update (day, slot, title, ingredients, archived_at) on public.meals to authenticated;
grant update (name, amount_cents, due_date, recurrence, last_paid_on, archived_at)
    on public.bills to authenticated;
grant update (title, body, pinned, archived_at) on public.notes to authenticated;
