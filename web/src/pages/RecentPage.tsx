import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Tool } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const MM_PER_INCH = 25.4;
const STORAGE_KEY_IMPERIAL = "datum-imperial";

function readImperialPref(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY_IMPERIAL) !== "false";
  } catch {
    return true;
  }
}

export function RecentPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const imperial = readImperialPref();

  useEffect(() => {
    async function fetchRecent() {
      const { data, error } = await supabase
        .from("tools")
        .select("*, libraries(library_name, vendor, source_modified_at)")
        .order("updated_at", { ascending: false });

      if (error) {
        console.error("Failed to fetch tools:", error);
        setLoading(false);
        return;
      }

      const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      const recent = (data ?? []).filter(
        (t) => t.libraries?.source_modified_at && t.libraries.source_modified_at > oneDayAgo
      );
      setTools(recent);
      setLoading(false);
    }
    fetchRecent();
  }, []);

  function fmt(val: number | null): string {
    if (val == null) return "\u2014";
    const v = imperial ? val / MM_PER_INCH : val;
    return imperial ? v.toFixed(4) : v.toFixed(2);
  }

  const dimUnit = imperial ? "in" : "mm";

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="space-y-4">
      <div>
        <Link to="/" className="text-sm text-muted-foreground hover:underline">
          &larr; All tools
        </Link>
      </div>

      <h1 className="text-2xl font-semibold tracking-tight">
        Recently Modified{" "}
        <span className="text-muted-foreground font-normal">
          ({tools.length})
        </span>
      </h1>
      <p className="text-sm text-muted-foreground">
        Tools whose Fusion Hub library was modified in the last 24 hours.
      </p>

      {tools.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No tools modified in the last 24 hours.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tools.map((tool) => (
            <Link key={tool.id} to={`/tools/${tool.id}`}>
              <Card className="transition-colors hover:bg-accent/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">
                    {tool.description || tool.product_id || "\u2014"}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-1.5 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{tool.type}</Badge>
                    {tool.plex_supply_item_id ? (
                      <Badge variant="default">Synced</Badge>
                    ) : (
                      <Badge variant="outline">Local</Badge>
                    )}
                  </div>
                  {tool.vendor && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Vendor</span>
                      <span>{tool.vendor}</span>
                    </div>
                  )}
                  {tool.product_id && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Part #</span>
                      <span className="font-mono text-xs">{tool.product_id}</span>
                    </div>
                  )}
                  {tool.geo_dc != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Diameter</span>
                      <span className="font-mono text-xs">{fmt(tool.geo_dc)} {dimUnit}</span>
                    </div>
                  )}
                  {tool.libraries?.library_name && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Library</span>
                      <span className="text-xs">{tool.libraries.library_name}</span>
                    </div>
                  )}
                  {tool.libraries?.source_modified_at && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Modified in Fusion</span>
                      <span className="text-xs">
                        {new Date(tool.libraries.source_modified_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
