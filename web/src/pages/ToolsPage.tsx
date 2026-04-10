import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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

export function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  const toolTypes = [...new Set(tools.map((t) => t.type))].sort();

  const filtered = tools.filter((t) => {
    if (typeFilter && t.type !== typeFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      t.description.toLowerCase().includes(q) ||
      t.product_id.toLowerCase().includes(q) ||
      t.vendor.toLowerCase().includes(q)
    );
  });

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
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search by description, part number, or vendor..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <div className="flex flex-wrap gap-1">
          <button
            onClick={() => setTypeFilter(null)}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
              typeFilter === null
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:bg-accent"
            }`}
          >
            All
          </button>
          {toolTypes.map((type) => (
            <button
              key={type}
              onClick={() => setTypeFilter(type === typeFilter ? null : type)}
              className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                typeFilter === type
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:bg-accent"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[200px] max-w-[320px]">Description</TableHead>
              <TableHead className="whitespace-nowrap">Part #</TableHead>
              <TableHead>Vendor</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right whitespace-nowrap">Dia (mm)</TableHead>
              <TableHead className="text-right whitespace-nowrap">OAL (mm)</TableHead>
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
                    {tool.geo_dc?.toFixed(2) ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {tool.geo_oal?.toFixed(2) ?? "—"}
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
