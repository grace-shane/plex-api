-- =========================================================================
-- Datum — initial schema (libraries / tools / cutting_presets)
-- =========================================================================
-- Replays the bulletforge fusion2plex_* design from 2026-04-08 against the
-- dedicated `datum` Supabase project, with the prefix dropped (no collision
-- risk in a dedicated project).
--
-- Source: bulletforge migrations 20260408171007 + 20260408171051,
-- bundled into one apply for the cutover on 2026-04-09.
--
-- Apply via Supabase SQL Editor against the `datum` project. Idempotent on a
-- fresh project; safe to replay only if the prior tables/triggers/policies
-- are dropped first.
-- =========================================================================

-- Generic updated_at trigger function. search_path pinned per Supabase
-- linter rule 0011.
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $fn$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$fn$;

-- =========================================================================
-- libraries — one row per ingested .json file
-- =========================================================================
CREATE TABLE public.libraries (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  library_name   TEXT NOT NULL,
  vendor         TEXT,
  file_path      TEXT,
  file_hash      TEXT,
  tool_count     INTEGER NOT NULL DEFAULT 0,
  unit_original  TEXT,
  ingested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX libraries_library_name_key
  ON public.libraries (library_name);

ALTER TABLE public.libraries ENABLE ROW LEVEL SECURITY;

-- Explicit deny-all anon policy on libraries.
-- Service role bypasses RLS implicitly, so ingest still writes. Anon +
-- authenticated cannot read libraries — only tools + cutting_presets are
-- exposed to the future React UI per spec.
CREATE POLICY libraries_deny_anon
  ON public.libraries
  FOR SELECT
  TO anon
  USING (false);

-- =========================================================================
-- tools — one row per cutting tool, geometry normalized to mm
-- =========================================================================
CREATE TABLE public.tools (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fusion_guid               TEXT NOT NULL UNIQUE,
  library_id                UUID REFERENCES public.libraries(id) ON DELETE SET NULL,

  -- Identity
  vendor                    TEXT NOT NULL,
  product_id                TEXT NOT NULL,
  description               TEXT NOT NULL,
  type                      TEXT NOT NULL,
  bmc                       TEXT,
  grade                     TEXT,
  reference_guid            TEXT,
  unit_original             TEXT,
  product_link              TEXT,
  tapered_type              TEXT,

  -- Geometry (all normalized to mm; nullable because vendor-specific)
  geo_dc                    FLOAT8,
  geo_nof                   FLOAT8,
  geo_oal                   FLOAT8,
  geo_lcf                   FLOAT8,
  geo_lb                    FLOAT8,
  geo_sfdm                  FLOAT8,
  geo_sig                   FLOAT8,
  geo_re                    FLOAT8,
  geo_nt                    FLOAT8,
  geo_ta                    FLOAT8,
  geo_ta2                   FLOAT8,
  geo_tp                    FLOAT8,
  geo_thread_profile_angle  FLOAT8,
  geo_tip_diameter          FLOAT8,
  geo_tip_length            FLOAT8,
  geo_tip_offset            FLOAT8,
  geo_assembly_gauge_length FLOAT8,
  geo_shoulder_diameter     FLOAT8,
  geo_shoulder_length       FLOAT8,
  geo_hand                  BOOLEAN,
  geo_csp                   BOOLEAN,

  -- Post-process (populated by CAM programmer, often zero in catalog libs)
  pp_number                 INTEGER,
  pp_turret                 INTEGER,
  pp_diameter_offset        INTEGER,
  pp_length_offset          INTEGER,
  pp_live                   BOOLEAN,
  pp_break_control          BOOLEAN,
  pp_manual_tool_change     BOOLEAN,
  pp_comment                TEXT,

  -- Passthrough
  shaft_segments            JSONB,

  -- Plex sync
  plex_supply_item_id       UUID,
  plex_synced_at            TIMESTAMPTZ,

  -- Timestamps
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX tools_product_vendor_idx
  ON public.tools (product_id, vendor);
CREATE INDEX tools_type_idx
  ON public.tools (type);
CREATE INDEX tools_library_id_idx
  ON public.tools (library_id);
CREATE INDEX tools_geo_dc_idx
  ON public.tools (geo_dc);

CREATE TRIGGER tools_updated_at
  BEFORE UPDATE ON public.tools
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.tools ENABLE ROW LEVEL SECURITY;

-- Anon role: read-only for future React UI
CREATE POLICY tools_anon_select
  ON public.tools
  FOR SELECT
  TO anon
  USING (true);

-- =========================================================================
-- cutting_presets — feeds/speeds per material per tool
-- =========================================================================
CREATE TABLE public.cutting_presets (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_id                 UUID NOT NULL REFERENCES public.tools(id) ON DELETE CASCADE,
  preset_guid             TEXT,
  name                    TEXT,
  description             TEXT,
  material_category       TEXT,
  material_query          TEXT,
  material_use_hardness   BOOLEAN,
  v_c                     FLOAT8,
  v_f                     FLOAT8,
  f_z                     FLOAT8,
  f_n                     FLOAT8,
  n                       FLOAT8,
  n_ramp                  FLOAT8,
  ramp_angle              FLOAT8,
  tool_coolant            TEXT,
  v_f_plunge              FLOAT8,
  v_f_ramp                FLOAT8,
  v_f_lead_in             FLOAT8,
  v_f_lead_out            FLOAT8,
  v_f_retract             FLOAT8,
  v_f_transition          FLOAT8,
  use_feed_per_revolution BOOLEAN,
  use_stepdown            BOOLEAN,
  use_stepover            BOOLEAN,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX cutting_presets_tool_id_idx
  ON public.cutting_presets (tool_id);
CREATE INDEX cutting_presets_name_idx
  ON public.cutting_presets (name);

ALTER TABLE public.cutting_presets ENABLE ROW LEVEL SECURITY;

-- Anon role: read-only for future React UI
CREATE POLICY cutting_presets_anon_select
  ON public.cutting_presets
  FOR SELECT
  TO anon
  USING (true);
