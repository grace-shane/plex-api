import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Library } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { relativeTime } from "@/lib/utils";

export function LibrariesPage() {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchLibraries() {
      const { data, error } = await supabase
        .from("libraries")
        .select("*")
        .order("library_name");

      if (error) {
        console.error("Failed to fetch libraries:", error);
      } else {
        setLibraries(data ?? []);
      }
      setLoading(false);
    }
    fetchLibraries();
  }, []);

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading libraries...</div>;
  }

  const lastSyncIso = libraries.reduce<string | null>((acc, lib) => {
    if (!lib.ingested_at) return acc;
    if (!acc || lib.ingested_at > acc) return lib.ingested_at;
    return acc;
  }, null);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-semibold tracking-tight">
          Libraries{" "}
          <span className="text-muted-foreground font-normal">
            ({libraries.length})
          </span>
        </h1>
        {lastSyncIso && (
          <div
            className="text-xs text-muted-foreground"
            title={new Date(lastSyncIso).toLocaleString()}
          >
            Last sync:{" "}
            <span className="font-medium text-foreground">
              {relativeTime(lastSyncIso)}
            </span>
          </div>
        )}
      </div>

      {libraries.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No libraries ingested yet. Run a sync to populate.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {libraries.map((lib) => (
            <Link key={lib.id} to={`/?library=${encodeURIComponent(lib.library_name)}`}>
              <Card className="transition-colors hover:bg-accent/50">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">{lib.library_name}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {lib.vendor && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Vendor</span>
                      <span>{lib.vendor}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Tools</span>
                    <Badge variant="secondary">{lib.tool_count}</Badge>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Last synced</span>
                    <span
                      title={new Date(lib.ingested_at).toLocaleString()}
                    >
                      {relativeTime(lib.ingested_at)}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
