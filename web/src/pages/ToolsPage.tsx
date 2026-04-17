import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { supabase } from "@/lib/supabase";
import type { Tool } from "@/lib/types";
import { relativeTime } from "@/lib/utils";
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

const STORAGE_KEY_INV_FILTER = "datum-inv-filter";

type InvStatus = "in_stock" | "out_of_stock" | "not_tracked" | "not_linked";
const ALL_INV_STATUSES: InvStatus[] = ["in_stock", "out_of_stock", "not_tracked", "not_linked"];
const INV_LABELS: Record<InvStatus, string> = {
  in_stock: "In stock",
  out_of_stock: "Out of stock",
  not_tracked: "Not tracked",
  not_linked: "Not linked",
};

function readInvFilter(): Set<InvStatus> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_INV_FILTER);
    if (raw) {
      const arr = JSON.parse(raw) as string[];
      const valid = arr.filter((s): s is InvStatus => ALL_INV_STATUSES.includes(s as InvStatus));
      if (valid.length > 0) return new Set(valid);
    }
  } catch {}
  return new Set<InvStatus>();
}

function getInvStatus(tool: Tool): InvStatus {
  if (!tool.plex_supply_item_id) return "not_linked";
  if (!tool.qty_tracked) return "not_tracked";
  return (tool.qty_on_hand ?? 0) > 0 ? "in_stock" : "out_of_stock";
}

type SortField =
  | "description"
  | "product_id"
  | "vendor"
  | "type"
  | "geo_dc"
  | "geo_oal"
  | "geo_nof"
  | "geo_re"
  | "qty_on_hand"
  | "plex";
type SortDir = "asc" | "desc";

function compare(a: Tool, b: Tool, field: SortField): number {
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
    case "geo_nof":
    case "geo_re":
    case "qty_on_hand": {
      // NULL sorts last regardless of direction (handled by using -Infinity
      // for asc — caller flips sign for desc, so -Inf stays at the end)
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

/** Custom multi-select dropdown that looks like a normal <select> */
function TypeDropdown({
  types,
  selected,
  onToggle,
  onClear,
}: {
  types: string[];
  selected: Set<string>;
  onToggle: (type: string) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const label =
    selected.size === 0
      ? "All types"
      : selected.size === 1
        ? [...selected][0]
        : `${selected.size} types`;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex h-9 items-center gap-1 rounded-md border border-border bg-background px-3 text-sm text-foreground"
      >
        {label}
        <svg
          className={`ml-1 h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M3 4.5 L6 7.5 L9 4.5" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-50 min-w-[180px] rounded-md border border-border bg-background py-1 shadow-md">
          {selected.size > 0 && (
            <button
              onClick={() => { onClear(); setOpen(false); }}
              className="w-full px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent"
            >
              Clear all
            </button>
          )}
          {types.map((type) => (
            <label
              key={type}
              className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={selected.has(type)}
                onChange={() => onToggle(type)}
                className="rounded"
              />
              {type}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/** Inventory status filter dropdown */
function InvStatusDropdown({
  selected,
  onToggle,
  onClear,
}: {
  selected: Set<InvStatus>;
  onToggle: (status: InvStatus) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const label =
    selected.size === 0
      ? "All inventory"
      : selected.size === 1
        ? INV_LABELS[[...selected][0]]
        : `${selected.size} statuses`;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex h-9 items-center gap-1 rounded-md border border-border bg-background px-3 text-sm text-foreground"
      >
        {label}
        <svg
          className={`ml-1 h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M3 4.5 L6 7.5 L9 4.5" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-50 min-w-[180px] rounded-md border border-border bg-background py-1 shadow-md">
          {selected.size > 0 && (
            <button
              onClick={() => { onClear(); setOpen(false); }}
              className="w-full px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent"
            >
              Clear all
            </button>
          )}
          {ALL_INV_STATUSES.map((status) => (
            <label
              key={status}
              className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={selected.has(status)}
                onChange={() => onToggle(status)}
                className="rounded"
              />
              {INV_LABELS[status]}
            </label>
          ))}
        </div>
      )}
    </div>
  );
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
  const [recentCount, setRecentCount] = useState<number | null>(null);
  const [invFilters, setInvFilters] = useState<Set<InvStatus>>(readInvFilter);

  useEffect(() => {
    async function fetchTools() {
      const { data, error } = await supabase
        .from("tools")
        .select("*, libraries(library_name, vendor, source_modified_at)")
        .order("vendor")
        .order("product_id");

      if (error) {
        console.error("Failed to fetch tools:", error);
      } else {
        setTools(data ?? []);

        // Count tools whose library was modified in the last 24h (per Fusion Hub)
        const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
        const recent = (data ?? []).filter(
          (t) => t.libraries?.source_modified_at && t.libraries.source_modified_at > oneDayAgo
        );
        setRecentCount(recent.length);
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

  const libraryParam = searchParams.get("library");
  const toolTypes = [...new Set(tools.map((t) => t.type))].sort();

  const filtered = tools.filter((t) => {
    if (typeFilters.size > 0 && !typeFilters.has(t.type)) return false;
    if (invFilters.size > 0 && !invFilters.has(getInvStatus(t))) return false;
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
    const c = compare(a, b, sortField);
    return sortDir === "asc" ? c : -c;
  });

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
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  function toggleInvFilter(status: InvStatus) {
    setInvFilters((prev) => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      try { localStorage.setItem(STORAGE_KEY_INV_FILTER, JSON.stringify([...next])); } catch {}
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
      {recentCount != null && recentCount > 0 && (
        <Link to="/recent">
          <div className="cursor-pointer rounded-md border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-800 transition-colors hover:bg-red-100 dark:border-red-800 dark:bg-red-950 dark:text-red-200 dark:hover:bg-red-900">
            <span className="font-medium">
              {recentCount} tool{recentCount !== 1 ? "s" : ""} modified in Fusion Hub in the last 24 hours
            </span>
            <span className="ml-2 text-red-600 dark:text-red-400">&rarr;</span>
          </div>
        </Link>
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
        <TypeDropdown
          types={toolTypes}
          selected={typeFilters}
          onToggle={toggleTypeFilter}
          onClear={() => setTypeFilters(new Set())}
        />
        <InvStatusDropdown
          selected={invFilters}
          onToggle={toggleInvFilter}
          onClear={() => { setInvFilters(new Set()); try { localStorage.removeItem(STORAGE_KEY_INV_FILTER); } catch {} }}
        />
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

      <div className="overflow-hidden rounded-lg border">
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
              <SortHeader field="geo_re" className="text-right whitespace-nowrap">Corner R ({dimUnit})</SortHeader>
              <SortHeader field="qty_on_hand" className="text-right whitespace-nowrap">On hand</SortHeader>
              <SortHeader field="plex">Plex</SortHeader>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="h-24 text-center text-muted-foreground">
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
                  <TableCell className="text-right font-mono text-sm">
                    {fmt(tool.geo_re)}
                  </TableCell>
                  <TableCell className="text-right text-sm whitespace-nowrap">
                    {!tool.plex_supply_item_id ? (
                      <span className="text-muted-foreground" title="No Plex link yet — will populate once writeback sync runs">&mdash;</span>
                    ) : !tool.qty_tracked ? (
                      <span className="text-muted-foreground" title="Linked to Plex but no adjustment history">Not tracked</span>
                    ) : (
                      <span
                        className="font-mono"
                        title={`Synced ${relativeTime(tool.qty_synced_at)}`}
                      >
                        {tool.qty_on_hand ?? 0} pcs
                      </span>
                    )}
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
