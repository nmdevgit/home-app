-- =====================================================================
-- NICK: paste into Supabase SQL Editor and Run, by hand, AFTER 0001-0006.
-- Safe to re-run. Does not touch existing data.
--
-- Adds grocery_items.price_cents (nullable whole cents, 0..100,000,000):
-- the price of a grocery line, shown for items in the cart.
-- Column-level UPDATE grant only (see 0003: a table-wide grant would let the
-- app edit ownership columns). All other grants are unchanged.
-- =====================================================================

alter table public.grocery_items add column if not exists price_cents integer;

alter table public.grocery_items drop constraint if exists grocery_items_price_check;
alter table public.grocery_items add constraint grocery_items_price_check
    check (price_cents is null or (price_cents >= 0 and price_cents <= 100000000));

grant update (price_cents) on public.grocery_items to authenticated;
