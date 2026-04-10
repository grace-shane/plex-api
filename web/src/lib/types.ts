export interface Library {
  id: string;
  library_name: string;
  vendor: string | null;
  file_path: string | null;
  file_hash: string | null;
  tool_count: number;
  unit_original: string | null;
  ingested_at: string;
  created_at: string;
}

export interface Tool {
  id: string;
  fusion_guid: string;
  library_id: string | null;

  // Identity
  vendor: string;
  product_id: string;
  description: string;
  type: string;
  bmc: string | null;
  grade: string | null;
  unit_original: string | null;
  product_link: string | null;

  // Geometry (mm)
  geo_dc: number | null;
  geo_nof: number | null;
  geo_oal: number | null;
  geo_lcf: number | null;
  geo_lb: number | null;
  geo_sfdm: number | null;
  geo_sig: number | null;
  geo_re: number | null;

  // Post-process
  pp_number: number | null;
  pp_comment: string | null;

  // Plex sync
  plex_supply_item_id: string | null;
  plex_synced_at: string | null;

  // Timestamps
  created_at: string;
  updated_at: string;

  // Joined
  libraries?: Pick<Library, "library_name" | "vendor"> | null;
}

export interface CuttingPreset {
  id: string;
  tool_id: string;
  preset_guid: string | null;
  name: string | null;
  description: string | null;
  material_category: string | null;
  material_query: string | null;
  v_c: number | null;
  v_f: number | null;
  f_z: number | null;
  f_n: number | null;
  n: number | null;
  tool_coolant: string | null;
  created_at: string;
}
