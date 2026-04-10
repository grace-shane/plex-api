import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Library } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function LibrariesPage() {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchLibraries() {
      const { data, error: err } = await supabase
        .from("libraries")
        .select("*")
        .order("library_name");

      if (err) {
        // libraries table has deny-all anon policy — expected with anon key
        if (err.code === "PGRST301" || err.message.includes("permission")) {
          setError(
            "Libraries table requires authenticated access. " +
            "The anon key can read tools and presets but not libraries directly."
          );
        } else {
          setError(err.message);
        }
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

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight">Libraries</h1>
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">
        Libraries{" "}
        <span className="text-muted-foreground font-normal">
          ({libraries.length})
        </span>
      </h1>

      {libraries.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No libraries ingested yet. Run a sync to populate.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {libraries.map((lib) => (
            <Card key={lib.id}>
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
                  <span className="text-muted-foreground">Ingested</span>
                  <span>{new Date(lib.ingested_at).toLocaleDateString()}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
