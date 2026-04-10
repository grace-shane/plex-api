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
const STORAGE_KEY_IMPERIAL = "datum-imperial";

function readImperialPref(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY_IMPERIAL) !== "false";
  } catch {
    return true;
  }
}

type SortField =
  | "description"
  | "product_id"
  | "vendor"
  | "type"
  | "geo_dc"
  | "geo_oal"
  | "geo_nof"
  | "plex";
type SortDir = "asc" | "desc";

function compare(a: Tool, b: Tool, field: SortField, imperial: boolean): number {
  switch (field) {
    case "description":
      return (a.description || "").localeCompare(b.description || "");
    case "product_id":
      return (a.product_id || "").localeCompare(b.product_id || "");
    case "vendor":
      return (a.vendor || "").localeCompare(b.vendor || "");
    case "type":
      return (a.type || "").localeCompare(b.type || "");
    case "geo_dc":
    case "geo_oal":
    case "geo_nof": {
      const av = a[field] ?? -Infinity;
      const bv = b[field] ?? -Infinity;
      return av - bv;
    }
    case "plex": {
      const ap = a.plex_supply_item_id ? 1 : 0;
      const bp = b.plex_supply_item_id ? 1 : 0;
      return ap - bp;
    }
    default:
      return 0;
  }
}

export function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [search, setSearch] = useState("");
  const [typeFilters, setTypeFilters] = useState<Set<string>>(new Set());
  const [imperial, setImperial] = useState(readImperialPref);
  const [loading, setLoading] = useState(true);
  const [searchParams] = useSearchParams();
  const [sortField, setSortField] = useState<SortField>("description");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

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

  function toggleImperial() {
    const next = !imperial;
    setImperial(next);
    try {
      localStorage.setItem(STORAGE_KEY_IMPERIAL, String(next));
    } catch {}
  }

  // Support ?library= param from Libraries page links
  const libraryParam = searchParams.get("library");

  const toolTypes = [...new Set(tools.map((t) => t.type))].sort();

  const filtered = tools.filter((t) => {
    if (typeFilters.size > 0 && !typeFilters.has(t.type)) return false;
    if (libraryParam && t.libraries?.library_name !== libraryParam) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      t.description.toLowerCase().includes(q) ||
      t.product_id.toLowerCase().includes(q) ||
      t.vendor.toLowerCase().includes(q)
    );
  });

  const sorted = [...filtered].sort((a, b) => {
    const c = compare(a, b, sortField, imperial);
    return sortDir === "asc" ? c : -c;
  });

  // Recent modifications (last 24h)
  const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const recentMods = tools.filter((t) => t.updated_at > oneDayAgo);

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  function toggleTypeFilter(type: string) {
    setTypeFilters((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }

  function fmt(val: number | null): string {
    if (val == null) return "\u2014";
    const v = imperial ? val / MM_PER_INCH : val;
    return imperial ? v.toFixed(4) : v.toFixed(2);
  }

  const dimUnit = imperial ? "in" : "mm";

  function SortHeader({ field, children, className }: { field: SortField; children: React.ReactNode; className?: string }) {
    const active = sortField === field;
    const arrow = active ? (sortDir === "asc" ? " \u25B2" : " \u25BC") : "";
    return (
      <TableHead
        className={`cursor-pointer select-none hover:text-foreground ${className ?? ""}`}
        onClick={() => handleSort(field)}
      >
        {children}{arrow}
      </TableHead>
    );
  }

  if (loading) {
    return <div className="py-12 text-center text-muted-foreground">Loading tools...</div>;
  }

  return (
    <div className="space-y-4">
      {recentMods.length > 0 && (
        <div className="rounded-md border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <span className="font-medium">{recentMods.length} tool{recentMods.length !== 1 ? "s" : ""} modified in the last 24 hours</span>
          {" \u2014 "}
          {recentMods.slice(0, 5).map((t) => t.description || t.product_id).join(", ")}
          {recentMods.length > 5 && `, and ${recentMods.length - 5} more`}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          Tools{" "}
          <span className="text-muted-foreground font-normal">
            ({sorted.length})
          </span>
        </h1>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <span className={imperial ? "text-muted-foreground" : "font-medium"}>mm</span>
          <button
            role="switch"
            aria-checked={imperial}
            onClick={toggleImperial}
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
          multiple
          value={[...typeFilters]}
          onChange={(e) => {
            const selected = new Set(
              [...e.target.selectedOptions].map((o) => o.value)
            );
            setTypeFilters(selected);
          }}
          className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground"
        >
          {toolTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        {typeFilters.size > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {[...typeFilters].map((t) => (
              <Badge
                key={t}
                variant="secondary"
                className="cursor-pointer"
                onClick={() => toggleTypeFilter(t)}
              >
                {t} &times;
              </Badge>
            ))}
            <button
              onClick={() => setTypeFilters(new Set())}
              className="text-xs text-muted-foreground hover:underline"
            >
              clear all
            </button>
          </div>
        )}
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
              <SortHeader field="description" className="min-w-[200px] max-w-[320px]">Description</SortHeader>
              <SortHeader field="product_id" className="whitespace-nowrap">Part #</SortHeader>
              <SortHeader field="vendor">Vendor</SortHeader>
              <SortHeader field="type">Type</SortHeader>
              <SortHeader field="geo_dc" className="text-right whitespace-nowrap">Dia ({dimUnit})</SortHeader>
              <SortHeader field="geo_oal" className="text-right whitespace-nowrap">OAL ({dimUnit})</SortHeader>
              <SortHeader field="geo_nof" className="text-right">Flutes</SortHeader>
              <SortHeader field="plex">Plex</SortHeader>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                  {tools.length === 0 ? "No tools in database. Run a sync to populate." : "No tools match your search."}
                </TableCell>
              </TableRow>
            ) : (
              sorted.map((tool) => (
                <TableRow key={tool.id}>
                  <TableCell className="max-w-[320px]">
                    <Link
                      to={`/tools/${tool.id}`}
                      className="block truncate font-medium text-foreground hover:underline"
                      title={tool.description}
                    >
                      {tool.description || "\u2014"}
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
                    {tool.geo_nof ?? "\u2014"}
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
