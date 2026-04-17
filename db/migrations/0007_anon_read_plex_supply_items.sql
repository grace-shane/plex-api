-- Allow anon read on plex_supply_items so the browser can render the
-- "Plex Staging Payload" card on ToolDetailPage (#81).
--
-- Migration 0006 enabled RLS on plex_supply_items but didn't add a
-- policy, so the anon client at web/src/pages/ToolDetailPage.tsx
-- `.from("plex_supply_items").select("*")` silently returns nothing.
-- Staging-payload data is already derivable from the anon-readable
-- tools rows — exposing it here just saves the browser from
-- recomputing the 6 fields.

CREATE POLICY "plex_supply_items_anon_read"
  ON public.plex_supply_items
  FOR SELECT
  TO anon
  USING (true);
