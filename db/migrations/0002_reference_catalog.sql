-- =========================================================================
-- Datum — reference_catalog table for vendor catalog cross-referencing
-- =========================================================================
-- Large vendor catalogs (Harvey, Helical, Garr, Guhring, Sandvik, etc.)
-- ingested from hsmtools downloads. Used to enrich shop tools that are
-- missing product_id by matching on (type, geometry).
--
-- Separate from the `tools` table so vendor catalog data doesn't mix
-- with Grace's actual shop tool inventory.
-- =========================================================================

CREATE TABLE public.reference_catalog (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  catalog_name    TEXT NOT NULL,       -- e.g. "Harvey Tool-End Mills"
  vendor          TEXT NOT NULL,
  product_id      TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  type            TEXT NOT NULL,       -- "flat end mill", "drill", etc.

  -- Geometry fingerprint (normalized to mm for consistent matching)
  geo_dc          FLOAT8,             -- cutting diameter
  geo_nof         FLOAT8,             -- number of flutes
  geo_oal         FLOAT8,             -- overall length
  geo_lcf         FLOAT8,             -- length of cut / flute length
  geo_sig         FLOAT8,             -- point angle (drills)

  unit_original   TEXT,               -- original unit before normalization

  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary lookup index: match shop tools by type + diameter + flute count
CREATE INDEX ref_catalog_match_idx
  ON public.reference_catalog (type, geo_dc, geo_nof);

-- Prevent duplicate entries from the same catalog
CREATE UNIQUE INDEX ref_catalog_dedup_idx
  ON public.reference_catalog (catalog_name, product_id);

CREATE INDEX ref_catalog_vendor_idx
  ON public.reference_catalog (vendor);

ALTER TABLE public.reference_catalog ENABLE ROW LEVEL SECURITY;

-- Service role only — no browser access to reference data
CREATE POLICY ref_catalog_deny_anon
  ON public.reference_catalog
  FOR SELECT
  TO anon
  USING (false);
