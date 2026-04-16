import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Tool, CuttingPreset, PlexSupplyItem } from "@/lib/types";
import { relativeTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const MM_PER_INCH = 25.4;
const STORAGE_KEY_IMPERIAL = "datum-imperial";

function readImperialPref(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY_IMPERIAL) !== "false";
  } catch {
    return true;
  }
}

function UnitToggle({ imperial, onToggle }: { imperial: boolean; onToggle: () => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <span className={imperial ? "text-muted-foreground" : "font-medium"}>mm</span>
      <button
        role="switch"
        aria-checked={imperial}
        onClick={onToggle}
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors ${
          imperial ? "bg-primary" : "bg-muted"
        }`}
      >
        <span
          className={`pointer-events-none block h-3.5 w-3.5 rounded-full bg-background shadow-sm transition-transform ${
            imperial ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      <span className={imperial ? "font-medium" : "text-muted-foreground"}>in</span>
    </label>
  );
}

function GeoRow({
  label,
  value,
  unit,
  imperial,
}: {
  label: string;
  value: number | null;
  unit?: string;
  imperial?: boolean;
}) {
  if (value == null) return null;

  let displayVal = value;
  let displayUnit = unit;
  if (unit === "mm" && imperial) {
    displayVal = value / MM_PER_INCH;
    displayUnit = "in";
  }

  return (
    <div className="flex justify-between py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-sm">
        {typeof displayVal === "number" ? displayVal.toFixed(imperial && unit === "mm" ? 4 : 3) : displayVal}
        {displayUnit && <span className="ml-1 text-muted-foreground">{displayUnit}</span>}
      </span>
    </div>
  );
}

export function ToolDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tool, setTool] = useState<Tool | null>(null);
  const [presets, setPresets] = useState<CuttingPreset[]>([]);
  const [staging, setStaging] = useState<PlexSupplyItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [imperial, setImperial] = useState(readImperialPref);

  useEffect(() => {
    async function fetch() {
      const [toolRes, presetsRes] = await Promise.all([
        supabase
          .from("tools")
          .select("*, libraries(library_name, vendor)")
          .eq("id", id!)
          .single(),
        supabase
          .from("cutting_presets")
          .select("*")
          .eq("tool_id", id!)
          .order("name"),
      ]);

      if (toolRes.data) {
        setTool(toolRes.data);
        // Fetch staging row (separate query — plex_supply_items keys on fusion_guid, not id)
        const { data: stagingData } = await supabase
          .from("plex_supply_items")
          .select("*")
          .eq("fusion_guid", toolRes.data.fusion_guid)
          .maybeSingle();
        if (stagingData) setStaging(stagingData);
      }
      if (presetsRes.data) setPresets(presetsRes.data);
      setLoading(false);
    }
    fetch();
  }, [id]);

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading...</div>;
  }

  if (!tool) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Tool not found.</p>
        <Link to="/" className="mt-2 text-sm underline">Back to tools</Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-muted-foreground hover:underline">
          &larr; All tools
        </Link>
      </div>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {tool.description}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {tool.vendor} &middot; {tool.product_id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <UnitToggle imperial={imperial} onToggle={() => {
            const next = !imperial;
            setImperial(next);
            try { localStorage.setItem(STORAGE_KEY_IMPERIAL, String(next)); } catch {}
          }} />
          <Badge variant="secondary">{tool.type}</Badge>
          {tool.plex_supply_item_id ? (
            <Badge variant="default">Synced to Plex</Badge>
          ) : (
            <Badge variant="outline">Local only</Badge>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">On hand</CardTitle>
        </CardHeader>
        <CardContent>
          {!tool.plex_supply_item_id ? (
            <p className="text-sm text-muted-foreground">
              Not linked to Plex — will populate once writeback sync runs.
            </p>
          ) : !tool.qty_tracked ? (
            <p className="text-sm text-muted-foreground">
              Linked to Plex but no adjustment history.
            </p>
          ) : (
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-semibold font-mono">
                {tool.qty_on_hand ?? 0}
              </span>
              <span className="text-muted-foreground">pcs</span>
              {tool.qty_synced_at && (
                <span className="ml-auto text-xs text-muted-foreground">
                  Synced {relativeTime(tool.qty_synced_at)}
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {staging && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              Plex Staging Payload
              {staging.plex_id ? (
                <Badge variant="default">
                  Posted {staging.posted_to_plex_at ? new Date(staging.posted_to_plex_at).toLocaleDateString() : ""}
                </Badge>
              ) : (
                <Badge variant="outline">Not posted</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Category</span>
              <span>{staging.category}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Group</span>
              <span>{staging.item_group ?? "\u2014"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Description</span>
              <span className="max-w-64 truncate">{staging.description ?? "\u2014"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Supply Item #</span>
              <span className="font-mono">{staging.supply_item_number ?? "\u2014"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Inventory Unit</span>
              <span>{staging.inventory_unit}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Type</span>
              <span>{staging.item_type}</span>
            </div>
            {staging.plex_id && (
              <>
                <Separator />
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Plex UUID</span>
                  <span className="max-w-48 truncate font-mono text-xs">{staging.plex_id}</span>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Geometry</CardTitle>
          </CardHeader>
          <CardContent className="space-y-0.5">
            <GeoRow label="Cutting diameter (DC)" value={tool.geo_dc} unit="mm" imperial={imperial} />
            <GeoRow label="Overall length (OAL)" value={tool.geo_oal} unit="mm" imperial={imperial} />
            <GeoRow label="Flute length (LCF)" value={tool.geo_lcf} unit="mm" imperial={imperial} />
            <GeoRow label="Body length (LB)" value={tool.geo_lb} unit="mm" imperial={imperial} />
            <GeoRow label="Shank diameter (SFDM)" value={tool.geo_sfdm} unit="mm" imperial={imperial} />
            <GeoRow label="Number of flutes (NOF)" value={tool.geo_nof} />
            <GeoRow label="Helix angle (SIG)" value={tool.geo_sig} unit="deg" />
            <GeoRow label="Corner radius (RE)" value={tool.geo_re} unit="mm" imperial={imperial} />
            {tool.geo_dc == null && tool.geo_oal == null && (
              <p className="py-2 text-sm text-muted-foreground">No geometry data available.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Identity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Vendor</span>
              <span>{tool.vendor}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Part number</span>
              <span className="font-mono">{tool.product_id}</span>
            </div>
            {tool.bmc && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Material (BMC)</span>
                <span>{tool.bmc}</span>
              </div>
            )}
            {tool.grade && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Grade</span>
                <span>{tool.grade}</span>
              </div>
            )}
            {tool.product_link && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Product link</span>
                <a
                  href={tool.product_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >
                  View
                </a>
              </div>
            )}
            {tool.libraries && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Library</span>
                <span>{tool.libraries.library_name}</span>
              </div>
            )}
            <Separator />
            <div className="flex justify-between">
              <span className="text-muted-foreground">Fusion GUID</span>
              <span className="max-w-48 truncate font-mono text-xs">{tool.fusion_guid}</span>
            </div>
            {tool.plex_supply_item_id && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Plex ID</span>
                <span className="max-w-48 truncate font-mono text-xs">{tool.plex_supply_item_id}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-muted-foreground">Last updated</span>
              <span>{new Date(tool.updated_at).toLocaleDateString()}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {tool.pp_number != null && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Post-Processor</CardTitle>
          </CardHeader>
          <CardContent className="space-y-0.5">
            <GeoRow label="Tool number (T)" value={tool.pp_number} />
            {tool.pp_comment && (
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Comment</span>
                <span className="text-sm">{tool.pp_comment}</span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div>
        <h2 className="mb-3 text-lg font-semibold">
          Cutting Presets{" "}
          <span className="font-normal text-muted-foreground">
            ({presets.length})
          </span>
        </h2>
        {presets.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No cutting presets for this tool.
          </p>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Material</TableHead>
                  <TableHead className="text-right">Vc (m/min)</TableHead>
                  <TableHead className="text-right">fz ({imperial ? "in" : "mm"})</TableHead>
                  <TableHead className="text-right">RPM</TableHead>
                  <TableHead className="text-right">Vf ({imperial ? "in/min" : "mm/min"})</TableHead>
                  <TableHead>Coolant</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {presets.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.name ?? "—"}</TableCell>
                    <TableCell>{p.material_category ?? "—"}</TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.v_c?.toFixed(1) ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.f_z == null
                        ? "—"
                        : imperial
                          ? (p.f_z / MM_PER_INCH).toFixed(5)
                          : p.f_z.toFixed(4)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.n?.toFixed(0) ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {p.v_f == null
                        ? "—"
                        : imperial
                          ? (p.v_f / MM_PER_INCH).toFixed(2)
                          : p.v_f.toFixed(1)}
                    </TableCell>
                    <TableCell>
                      {p.tool_coolant ? (
                        <Badge variant="secondary">{p.tool_coolant}</Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
