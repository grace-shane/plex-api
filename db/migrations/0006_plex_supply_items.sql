-- =========================================================================
-- Datum — plex_supply_items staging table
-- =========================================================================
-- Mirrors the 6-field Plex supply-item POST payload shape (see docs/
-- Plex_API_Reference.md §3.5). One row per tools.fusion_guid, containing
-- exactly what would be POSTed to inventory/v1/inventory-definitions/
-- supply-items when #3 writeback runs. Plex-assigned UUID lands in
-- plex_id after a successful POST; until then NULL.
--
-- Design:
--   - fusion_guid PRIMARY KEY (1:1 with tools) — not a surrogate id
--   - Plex field names with reserved words (group, type) are renamed to
--     item_group / item_type here; the payload builder in #3 does the
--     one-line camelCase + rename translation at serialization time
--   - Defaults cover universally-true values (category, inventory_unit,
--     item_type) so inserts need only 3 derived columns
--   - Two partial indexes: reverse-lookup by plex_id, and "unposted"
--     queue for the writeback worker
--   - supply_item_number is NOT UNIQUE locally — let Plex 409 on collision
--
-- Issue: #3 (writeback), staging precursor requested 2026-04-15
-- =========================================================================

CREATE TABLE public.plex_supply_items (
  fusion_guid          TEXT PRIMARY KEY
                         REFERENCES public.tools(fusion_guid) ON DELETE CASCADE,

  -- Plex payload fields (snake_case locally; payload builder converts
  -- to camelCase on the wire and renames item_group -> "group",
  -- item_type -> "type").
  category             TEXT NOT NULL DEFAULT 'Tools & Inserts',
  description          TEXT,
  item_group           TEXT,
  inventory_unit       TEXT NOT NULL DEFAULT 'Ea',
  supply_item_number   TEXT,
  item_type            TEXT NOT NULL DEFAULT 'SUPPLY',

  -- Plex-assigned UUID, NULL until #3 writeback POST succeeds.
  plex_id              UUID,

  -- Audit
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  posted_to_plex_at    TIMESTAMPTZ
);

CREATE INDEX plex_supply_items_plex_id_idx
  ON public.plex_supply_items(plex_id) WHERE plex_id IS NOT NULL;

CREATE INDEX plex_supply_items_unposted_idx
  ON public.plex_supply_items(fusion_guid) WHERE plex_id IS NULL;

CREATE TRIGGER plex_supply_items_set_updated_at
  BEFORE UPDATE ON public.plex_supply_items
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.plex_supply_items ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.plex_supply_items IS
  'Staging layer mirroring the 6 Plex supply-item payload fields (#3 writeback target). One row per tools.fusion_guid. plex_id is NULL until Plex assigns one on POST.';

COMMENT ON COLUMN public.plex_supply_items.plex_id IS
  'UUID assigned by Plex on POST to /inventory/v1/inventory-definitions/supply-items. Also mirrored into tools.plex_supply_item_id with plex_linked_by=''writeback''.';

COMMENT ON COLUMN public.plex_supply_items.item_group IS
  'Plex "group" field (reserved word locally). Mapped from tools.type via the spec in Notion Supabase Schema Design.';

COMMENT ON COLUMN public.plex_supply_items.item_type IS
  'Plex "type" field (reserved word locally). Default "SUPPLY"; may become "SUPPLY-FUSION" if Plex accepts a custom type (per 2026-04-08 decision).';

COMMENT ON COLUMN public.plex_supply_items.posted_to_plex_at IS
  'Timestamp of the most recent successful POST to Plex for this row. NULL means never posted; non-NULL with NULL plex_id would indicate a data-integrity bug.';
