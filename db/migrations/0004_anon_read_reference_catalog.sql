-- Allow anon read on reference_catalog (public vendor data).
DROP POLICY IF EXISTS "ref_catalog_deny_anon" ON reference_catalog;

CREATE POLICY "ref_catalog_anon_read"
  ON reference_catalog
  FOR SELECT
  TO anon
  USING (true);
