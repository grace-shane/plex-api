import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Tool } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const MM_PER_INCH = 25.4;

interface RefMatch {
  product_id: string;
  vendor: string;
  geo_oal: number | null;
  description: string | null;
  exact_oal: boolean;
}

interface ToolFix extends Tool {
  generatedDescription: string;
  refMatches: RefMatch[];
  selectedRef: RefMatch | null;
  accepted: boolean;
  useVendor: string;
  useProductId: string;
}

// ─── Description generation ────────────────────────────────

function generateDescription(tool: Tool): string {
  const isInches = tool.unit_original?.toLowerCase() === "inches";
  const unit = isInches ? '"' : "mm";
  const parts: string[] = [];

  if (tool.geo_dc != null) {
    const val = isInches ? tool.geo_dc / MM_PER_INCH : tool.geo_dc;
    parts.push(`${formatDim(val, isInches)}${unit}`);
  }
  if (tool.type) parts.push(tool.type);
  if (tool.geo_nof != null) parts.push(`${tool.geo_nof}FL`);
  if (tool.geo_oal != null) {
    const val = isInches ? tool.geo_oal / MM_PER_INCH : tool.geo_oal;
    parts.push(`${formatDim(val, isInches)}${unit} OAL`);
  }

  return parts.join(" ").toUpperCase();
}

function formatDim(val: number, isInches: boolean): string {
  if (isInches) {
    const frac = toFraction(val);
    if (frac) return frac;
    return val.toFixed(4);
  }
  return val.toFixed(2);
}

function toFraction(val: number): string | null {
  const fractions: [number, string][] = [
    [1/64,"1/64"],[1/32,"1/32"],[3/64,"3/64"],[1/16,"1/16"],
    [5/64,"5/64"],[3/32,"3/32"],[7/64,"7/64"],[1/8,"1/8"],
    [9/64,"9/64"],[5/32,"5/32"],[11/64,"11/64"],[3/16,"3/16"],
    [13/64,"13/64"],[7/32,"7/32"],[15/64,"15/64"],[1/4,"1/4"],
    [17/64,"17/64"],[9/32,"9/32"],[19/64,"19/64"],[5/16,"5/16"],
    [21/64,"21/64"],[11/32,"11/32"],[23/64,"23/64"],[3/8,"3/8"],
    [25/64,"25/64"],[13/32,"13/32"],[27/64,"27/64"],[7/16,"7/16"],
    [29/64,"29/64"],[15/32,"15/32"],[31/64,"31/64"],[1/2,"1/2"],
    [33/64,"33/64"],[17/32,"17/32"],[35/64,"35/64"],[9/16,"9/16"],
    [37/64,"37/64"],[19/32,"19/32"],[39/64,"39/64"],[5/8,"5/8"],
    [41/64,"41/64"],[21/32,"21/32"],[43/64,"43/64"],[11/16,"11/16"],
    [45/64,"45/64"],[23/32,"23/32"],[47/64,"47/64"],[3/4,"3/4"],
    [49/64,"49/64"],[25/32,"25/32"],[51/64,"51/64"],[13/16,"13/16"],
    [53/64,"53/64"],[27/32,"27/32"],[55/64,"55/64"],[7/8,"7/8"],
    [57/64,"57/64"],[29/32,"29/32"],[59/64,"59/64"],[15/16,"15/16"],
    [61/64,"61/64"],[31/32,"31/32"],[63/64,"63/64"],
    [1,"1"],[1.5,"1-1/2"],[2,"2"],[2.5,"2-1/2"],[3,"3"],[4,"4"],
  ];
  for (const [num, str] of fractions) {
    if (Math.abs(val - num) < 0.0005) return str;
  }
  const whole = Math.floor(val);
  if (whole >= 1 && val - whole > 0.001) {
    const remainder = val - whole;
    for (const [num, str] of fractions) {
      if (Math.abs(remainder - num) < 0.0005) return `${whole}-${str}`;
    }
  }
  return null;
}

// ─── Reference catalog lookup ──────────────────────────────

async function lookupRefs(
  tools: Tool[]
): Promise<Map<string, RefMatch[]>> {
  const result = new Map<string, RefMatch[]>();

  // Build unique geometry queries
  const geometries = new Map<string, Tool[]>();
  for (const t of tools) {
    if (t.geo_dc == null || t.geo_nof == null) continue;
    const key = `${t.type}|${t.geo_dc.toFixed(3)}|${t.geo_nof}`;
    const list = geometries.get(key) ?? [];
    list.push(t);
    geometries.set(key, list);
  }

  for (const [, group] of geometries) {
    const t = group[0];
    const dc = t.geo_dc!;
    const nof = t.geo_nof!;

    const { data } = await supabase
      .from("reference_catalog")
      .select("product_id, vendor, geo_oal, description")
      .eq("type", t.type)
      .gte("geo_dc", dc - 0.05)
      .lte("geo_dc", dc + 0.05)
      .eq("geo_nof", nof)
      .limit(20);

    if (!data || data.length === 0) continue;

    for (const tool of group) {
      // Sort matches: exact OAL first, then by OAL distance
      const matches: RefMatch[] = data.map((r) => ({
        product_id: r.product_id,
        vendor: r.vendor ?? "",
        geo_oal: r.geo_oal,
        description: r.description,
        exact_oal: r.geo_oal != null && tool.geo_oal != null &&
          Math.abs(r.geo_oal - tool.geo_oal) < 0.5,
      }));

      matches.sort((a, b) => {
        if (a.exact_oal && !b.exact_oal) return -1;
        if (!a.exact_oal && b.exact_oal) return 1;
        const da = a.geo_oal != null && tool.geo_oal != null
          ? Math.abs(a.geo_oal - tool.geo_oal) : 999;
        const db = b.geo_oal != null && tool.geo_oal != null
          ? Math.abs(b.geo_oal - tool.geo_oal) : 999;
        return da - db;
      });

      result.set(tool.id, matches.slice(0, 5));
    }
  }

  return result;
}

// ─── Fusion script builder ─────────────────────────────────

function buildFusionScript(tools: ToolFix[]): string {
  const accepted = tools.filter((t) => t.accepted);
  if (accepted.length === 0) return "";

  const byLibrary = new Set(accepted.map((t) => t.libraries?.library_name ?? "Unknown"));

  const entries = accepted.map((t) => {
    const desc = t.generatedDescription.replace(/"/g, '\\"');
    const vendor = (t.useVendor || "MSC").replace(/"/g, '\\"');
    const pid = (t.useProductId || "").replace(/"/g, '\\"');
    return `    "${t.fusion_guid}": {"description": "${desc}", "vendor": "${vendor}", "product_id": "${pid}"},`;
  }).join("\n");

  return `# ─────────────────────────────────────────────────────────────
# Datum — Fill Missing Tool Data
# Generated by Datum UI (${new Date().toISOString().slice(0, 10)})
# ─────────────────────────────────────────────────────────────
# Paste into Fusion 360: Utilities → Scripts and Add-Ins → +
# Create a new script, paste into the .py file, and Run.
#
# Libraries: ${[...byLibrary].join(", ")}
# Tools to update: ${accepted.length}
# ─────────────────────────────────────────────────────────────

import adsk.core
import adsk.cam
import traceback

UPDATES = {
${entries}
}

FIELD_MAP = {
    "description": "description",
    "vendor": "vendor",
    "product_id": "product-id",
}

def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    updated = 0

    try:
        camMgr = adsk.cam.CAMManager.get()
        libMgr = camMgr.libraryManager
        toolLibs = libMgr.toolLibraries

        for url in toolLibs.urls:
            lib = toolLibs.toolLibraryAtURL(url)
            lib_changed = False

            for i in range(lib.count):
                tool = lib.item(i)
                guid_param = tool.parameters.itemByName("guid")
                if not guid_param:
                    continue
                guid = guid_param.value.stringValue
                if guid not in UPDATES:
                    continue

                fields = UPDATES[guid]
                for key, fusion_name in FIELD_MAP.items():
                    val = fields.get(key, "")
                    if not val:
                        continue
                    param = tool.parameters.itemByName(fusion_name)
                    if param:
                        param.value.stringValue = val
                        lib_changed = True

                updated += 1

            if lib_changed:
                toolLibs.replaceToolLibrary(url, lib)

        ui.messageBox(
            f"Done! Updated {updated} of {len(UPDATES)} tools.\\n"
            f"Let Fusion sync to the cloud, then run a Datum nightly sync.",
            "Datum — Tool Update"
        )

    except Exception:
        ui.messageBox("Error:\\n" + traceback.format_exc(), "Datum Script Error")
`;
}

// ─── Component ─────────────────────────────────────────────

export function ScriptsPage() {
  const [tools, setTools] = useState<ToolFix[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    async function fetchData() {
      const { data, error } = await supabase
        .from("tools")
        .select("*, libraries(library_name, vendor, source_modified_at)")
        .or("description.is.null,description.eq.")
        .order("type")
        .order("geo_dc");

      if (error) {
        console.error("Failed to fetch tools:", error);
        setLoading(false);
        return;
      }

      const rawTools = data ?? [];
      const refs = await lookupRefs(rawTools);

      const fixes: ToolFix[] = rawTools.map((t) => {
        const matches = refs.get(t.id) ?? [];
        const best = matches.find((m) => m.exact_oal) ?? matches[0] ?? null;
        return {
          ...t,
          generatedDescription: generateDescription(t),
          refMatches: matches,
          selectedRef: best,
          accepted: true,
          useVendor: best?.vendor || "MSC",
          useProductId: best?.product_id || "",
        };
      });

      setTools(fixes);
      setLoading(false);
    }
    fetchData();
  }, []);

  function updateTool(id: string, patch: Partial<ToolFix>) {
    setTools((prev) => prev.map((t) => t.id === id ? { ...t, ...patch } : t));
  }

  function selectRef(toolId: string, ref: RefMatch | null) {
    updateTool(toolId, {
      selectedRef: ref,
      useVendor: ref?.vendor || "MSC",
      useProductId: ref?.product_id || "",
    });
  }

  const acceptedCount = tools.filter((t) => t.accepted).length;
  const script = buildFusionScript(tools);

  async function copyScript() {
    try {
      await navigator.clipboard.writeText(script);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-muted-foreground hover:underline">
          &larr; All tools
        </Link>
      </div>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Fix Missing Tool Data{" "}
          <span className="text-muted-foreground font-normal">
            ({tools.length} tools, {acceptedCount} accepted)
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Description generated from geometry. Vendor and part # suggested from the
          reference catalog (82k tools). Review each card, then copy the Fusion script.
        </p>
      </div>

      {tools.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            All tools have descriptions. Nothing to fix.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="space-y-3">
            {tools.map((tool) => (
              <Card
                key={tool.id}
                className={tool.accepted ? "" : "opacity-50"}
              >
                <CardContent className="py-4">
                  <div className="flex items-start gap-4">
                    {/* Accept checkbox */}
                    <label className="flex items-center pt-1">
                      <input
                        type="checkbox"
                        checked={tool.accepted}
                        onChange={(e) => updateTool(tool.id, { accepted: e.target.checked })}
                        className="rounded"
                      />
                    </label>

                    {/* Main info */}
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-sm font-medium">
                          {tool.generatedDescription}
                        </span>
                        <Badge variant="secondary">{tool.type}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {tool.libraries?.library_name}
                        </span>
                      </div>

                      {/* Vendor + Part # fields */}
                      <div className="flex items-center gap-3 text-sm">
                        <label className="flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Vendor</span>
                          <input
                            type="text"
                            value={tool.useVendor}
                            onChange={(e) => updateTool(tool.id, { useVendor: e.target.value })}
                            className="h-7 w-32 rounded border border-border bg-background px-2 text-xs font-mono"
                          />
                        </label>
                        <label className="flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Part #</span>
                          <input
                            type="text"
                            value={tool.useProductId}
                            onChange={(e) => updateTool(tool.id, { useProductId: e.target.value })}
                            className="h-7 w-40 rounded border border-border bg-background px-2 text-xs font-mono"
                          />
                        </label>
                      </div>

                      {/* Reference catalog matches */}
                      {tool.refMatches.length > 0 && (
                        <div className="space-y-1">
                          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                            Reference catalog matches
                          </span>
                          <div className="flex flex-wrap gap-1">
                            {tool.refMatches.map((ref, i) => (
                              <button
                                key={i}
                                onClick={() => selectRef(tool.id, ref)}
                                className={`rounded border px-2 py-0.5 text-[11px] font-mono transition-colors ${
                                  tool.selectedRef === ref
                                    ? "border-primary bg-primary/10 text-foreground"
                                    : "border-border text-muted-foreground hover:bg-accent"
                                }`}
                                title={ref.description || undefined}
                              >
                                {ref.vendor} {ref.product_id}
                                {ref.exact_oal && (
                                  <span className="ml-1 text-green-600">*</span>
                                )}
                              </button>
                            ))}
                            <button
                              onClick={() => selectRef(tool.id, null)}
                              className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
                                tool.selectedRef === null
                                  ? "border-primary bg-primary/10 text-foreground"
                                  : "border-border text-muted-foreground hover:bg-accent"
                              }`}
                            >
                              MSC (no part #)
                            </button>
                          </div>
                          {tool.refMatches.some((r) => r.exact_oal) && (
                            <span className="text-[10px] text-green-600">* exact OAL match</span>
                          )}
                        </div>
                      )}
                      {tool.refMatches.length === 0 && (
                        <span className="text-[10px] text-muted-foreground">
                          No reference catalog match — defaulting to MSC
                        </span>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {acceptedCount > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">
                    Fusion 360 Script ({acceptedCount} tools)
                  </CardTitle>
                  <button
                    onClick={copyScript}
                    className="rounded-md border border-border px-3 py-1.5 text-xs transition-colors hover:bg-accent"
                  >
                    {copied ? "Copied!" : "Copy to clipboard"}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Utilities &rarr; Scripts and Add-Ins &rarr; Create a new script &rarr; paste &rarr; Run
                </p>
              </CardHeader>
              <CardContent>
                <pre className="max-h-96 overflow-auto rounded-md bg-muted p-4 text-xs font-mono whitespace-pre">
                  {script}
                </pre>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
