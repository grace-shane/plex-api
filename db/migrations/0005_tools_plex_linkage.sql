-- =========================================================================
-- Datum — tools.plex_* linkage + qty cache columns
-- =========================================================================
-- Adds Plex linkage provenance and on-hand-qty cache columns to the tools
-- table, supporting the inventory display work on datum.graceops.dev.
--
-- Supersedes the separate tool_plex_links table originally planned in #74:
-- the tools table already carries plex_supply_item_id UUID (from
-- 0001_initial_schema.sql line 116), so linkage is a property of the tool
-- rather than a separate entity. Flattening avoids a join on every
-- ToolsPage load.
--
-- Issue: #75 (parent #49)
-- =========================================================================

ALTER TABLE public.tools
  ADD COLUMN plex_linked_by TEXT
    CHECK (plex_linked_by IS NULL OR plex_linked_by IN ('manual', 'writeback', 'sync')),
  ADD COLUMN plex_linked_at TIMESTAMPTZ,
  ADD COLUMN qty_on_hand    NUMERIC,
  ADD COLUMN qty_tracked    BOOLEAN,
  ADD COLUMN qty_synced_at  TIMESTAMPTZ;

-- Reverse lookup: "which tool is linked to this Plex supply-item?"
-- Partial because most rows will have NULL plex_supply_item_id until
-- #3 writeback catches up.
CREATE INDEX tools_plex_supply_item_id_idx
  ON public.tools (plex_supply_item_id)
  WHERE plex_supply_item_id IS NOT NULL;

-- Column semantics documented in the DB so they're visible in the
-- Supabase Table Editor + `psql \d+ tools`.
COMMENT ON COLUMN public.tools.plex_linked_by IS
  'How plex_supply_item_id was populated. ''manual'' = hand-curated, ''writeback'' = captured from #3 Fusion->Plex write sync response, ''sync'' = automated description-match pass. NULL = not linked.';

COMMENT ON COLUMN public.tools.plex_linked_at IS
  'When plex_supply_item_id was set. NULL = not linked.';

COMMENT ON COLUMN public.tools.qty_on_hand IS
  'Running balance derived from summing Plex inventory-history/item-adjustments for plex_supply_item_id. NULL = unknown (tool not linked, or not yet synced, or no adjustment history).';

COMMENT ON COLUMN public.tools.qty_tracked IS
  'TRUE if the linked Plex supply-item has one or more adjustment records. FALSE = linked but Plex has no inventory history for it (the 97% case per the 2026-04-15 probe). NULL = not yet checked.';

COMMENT ON COLUMN public.tools.qty_synced_at IS
  'When qty_on_hand / qty_tracked were last refreshed from Plex. Distinct from plex_synced_at (the Fusion->Plex write-sync timestamp, populated by #3).';
