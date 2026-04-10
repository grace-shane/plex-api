-- Track when the library file was last modified in Fusion Hub (APS).
-- Distinct from ingested_at (when we last synced) and updated_at (Supabase trigger).
ALTER TABLE public.libraries
  ADD COLUMN IF NOT EXISTS source_modified_at TIMESTAMPTZ;

COMMENT ON COLUMN public.libraries.source_modified_at
  IS 'lastModifiedTime from APS Data Management API — when the .tools file was last saved in Fusion Hub';
