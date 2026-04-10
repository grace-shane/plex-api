import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Tool } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const MM_PER_INCH = 25.4;

export function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [imperial, setImperial] = useState(false);
  const [loading, setLoading] = useState(true);
  const [searchParams] = useSearchParams();

  useEffect(() => {
    async function fetchTools() {
      const { data, error } = await supabase
        .from("tools")
        .select("*, libraries(library_name, vendor)")
        .order("vendor")
        .order("product_id");

      if (error) {
        console.error("Failed to fetch tools:", error);
      } else {
        setTools(data ?? []);
      }
      setLoading(false);
    }
    fetchTools();
  }, []);

  // Support ?library= param from Libraries page links
  const libraryParam = searchParams.get("library");

  const toolTypes = [...new Set(tools.map((t) => t.type))].sort();

  const filtered = tools.filter((t) => {
    if (typeFilter && t.type !== typeFilter) return false;
    if (libraryParam && t.libraries?.library_name !== libraryParam) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      t.description.toLowerCase().includes(q) ||
      t.product_id.toLowerCase().includes(q) ||
      t.vendor.toLowerCase().includes(q)
    );
  });

  function fmt(val: number | null): string {
    if (val == null) return "—";
    const v = imperial ? val / MM_PER_INCH : val;
    return imperial ? v.toFixed(4) : v.toFixed(2);
  }

  const dimUnit = imperial ? "in" : "mm";

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading tools...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          Tools{" "}
          <span className="text-muted-foreground font-normal">
            ({filtered.length})
          </span>
        </h1>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <span className={imperial ? "text-muted-foreground" : "font-medium"}>mm</span>
          <button
            role="switch"
            aria-checked={imperial}
            onClick={() => setImperial(!imperial)}
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
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search by description, part number, or vendor..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <select
          value={typeFilter ?? ""}
          onChange={(e) => setTypeFilter(e.target.value || null)}
          className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
        >
          <option value="">All types</option>
          {toolTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        {libraryParam && (
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary">{libraryParam}</Badge>
            <Link to="/" className="text-xs text-muted-foreground hover:underline">
              clear
            </Link>
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px] max-w-[320px]">Description</TableHead>
              <TableHead className="whitespace-nowrap">Part #</TableHead>
              <TableHead>Vendor</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right whitespace-nowrap">Dia ({dimUnit})</TableHead>
              <TableHead className="text-right whitespace-nowrap">OAL ({dimUnit})</TableHead>
              <TableHead className="text-right">Flutes</TableHead>
              <TableHead>Plex</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                  {tools.length === 0 ? "No tools in database. Run a sync to populate." : "No tools match your search."}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((tool) => (
                <TableRow key={tool.id}>
                  <TableCell className="max-w-[320px]">
                    <Link
                      to={`/tools/${tool.id}`}
                      className="block truncate font-medium text-foreground hover:underline"
                      title={tool.description}
                    >
                      {tool.description || "—"}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {tool.product_id}
                  </TableCell>
                  <TableCell>{tool.vendor}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{tool.type}</Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {fmt(tool.geo_dc)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {fmt(tool.geo_oal)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {tool.geo_nof ?? "—"}
                  </TableCell>
                  <TableCell>
                    {tool.plex_supply_item_id ? (
                      <Badge variant="default">Synced</Badge>
                    ) : (
                      <Badge variant="outline">Local</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
