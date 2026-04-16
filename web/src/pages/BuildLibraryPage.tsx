import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { ReferenceRow } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const MM_PER_INCH = 25.4;
const PAGE_SIZE = 50;

// ── Fusion 360 JSON export helpers ──────────────────────
function refToFusionTool(ref: ReferenceRow): Record<string, unknown> {
  const isInches = ref.unit_original?.toLowerCase() === "inches";
  const scale = isInches ? 1 / MM_PER_INCH : 1; // DB stores mm; convert back if original was inches
  const unit = isInches ? "inches" : "millimeters";

  return {
    guid: crypto.randomUUID(),
    type: ref.type,
    unit,
    vendor: ref.vendor,
    "product-id": ref.product_id,
    description: ref.description,
    BMC: "carbide",
    GRADE: "",
    geometry: {
      ...(ref.geo_dc != null && { DC: ref.geo_dc * scale }),
      ...(ref.geo_nof != null && { NOF: ref.geo_nof }),
      ...(ref.geo_oal != null && { OAL: ref.geo_oal * scale }),
      ...(ref.geo_lcf != null && { LCF: ref.geo_lcf * scale }),
      ...(ref.geo_sig != null && { SIG: ref.geo_sig }),
      CSP: false,
      HAND: true,
    },
    "post-process": {
      number: 0,
      turret: 0,
      "diameter-offset": 0,
      "length-offset": 0,
      live: true,
      "break-control": false,
      "manual-tool-change": false,
      comment: "",
    },
    "start-values": { presets: [] },
    expressions: {},
  };
}

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Multi-select dropdown (reused pattern) ──────────────
function FilterDropdown({
  label: dropLabel,
  options,
  selected,
  onToggle,
  onClear,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onToggle: (val: string) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const display =
    selected.size === 0
      ? dropLabel
      : selected.size === 1
        ? [...selected][0]
        : `${selected.size} selected`;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex h-9 items-center gap-1 rounded-md border border-border bg-background px-3 text-sm text-foreground"
      >
        {display}
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
        <div className="absolute left-0 top-10 z-50 max-h-64 min-w-[200px] overflow-y-auto rounded-md border border-border bg-background py-1 shadow-md">
          {selected.size > 0 && (
            <button
              onClick={() => { onClear(); setOpen(false); }}
              className="w-full px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent"
            >
              Clear all
            </button>
          )}
          {options.map((opt) => (
            <label
              key={opt}
              className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={selected.has(opt)}
                onChange={() => onToggle(opt)}
                className="rounded"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main page ───────────────────────────────────────────
export function BuildLibraryPage() {
  const [results, setResults] = useState<ReferenceRow[]>([]);
  const [cart, setCart] = useState<Map<string, ReferenceRow>>(new Map());
  const [search, setSearch] = useState("");
  const [vendorFilter, setVendorFilter] = useState<Set<string>>(new Set());
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [vendors, setVendors] = useState<string[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [libraryName, setLibraryName] = useState("My Library");

  // Fetch distinct vendors and types on mount
  useEffect(() => {
    async function fetchMeta() {
      const [vRes, tRes] = await Promise.all([
        supabase.from("reference_catalog").select("vendor").limit(1000),
        supabase.from("reference_catalog").select("type").limit(1000),
      ]);
      if (vRes.data) {
        const unique = [...new Set(vRes.data.map((r: { vendor: string }) => r.vendor))].sort();
        setVendors(unique);
      }
      if (tRes.data) {
        const unique = [...new Set(tRes.data.map((r: { type: string }) => r.type))].sort();
        setTypes(unique);
      }
    }
    fetchMeta();
  }, []);

  // Search the catalog
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchResults(0);
    }, 300); // debounce
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, vendorFilter, typeFilter]);

  async function fetchResults(pageNum: number) {
    setLoading(true);
    setPage(pageNum);

    let query = supabase
      .from("reference_catalog")
      .select("*", { count: "exact" })
      .order("vendor")
      .order("product_id")
      .range(pageNum * PAGE_SIZE, (pageNum + 1) * PAGE_SIZE - 1);

    if (search.trim()) {
      // Use ilike for text search on description and product_id
      const q = `%${search.trim()}%`;
      query = query.or(`description.ilike.${q},product_id.ilike.${q}`);
    }

    if (vendorFilter.size > 0) {
      query = query.in("vendor", [...vendorFilter]);
    }
    if (typeFilter.size > 0) {
      query = query.in("type", [...typeFilter]);
    }

    const { data, count, error } = await query;
    if (error) {
      console.error("Reference catalog query failed:", error);
    } else {
      setResults(data ?? []);
      setTotalCount(count);
    }
    setLoading(false);
  }

  function toggleCart(row: ReferenceRow) {
    setCart((prev) => {
      const next = new Map(prev);
      if (next.has(row.id)) {
        next.delete(row.id);
      } else {
        next.set(row.id, row);
      }
      return next;
    });
  }

  function addAllVisible() {
    setCart((prev) => {
      const next = new Map(prev);
      for (const r of results) next.set(r.id, r);
      return next;
    });
  }

  function handleExport() {
    const tools = [...cart.values()].map(refToFusionTool);
    downloadJson({ data: tools, version: 2 }, `${libraryName.replace(/\s+/g, "_")}.json`);
  }

  function toggleFilter(set: Set<string>, val: string, setter: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    setter(next);
  }

  function fmtMm(val: number | null): string {
    if (val == null) return "\u2014";
    return val.toFixed(2);
  }

  const totalPages = totalCount != null ? Math.ceil(totalCount / PAGE_SIZE) : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          Build a Library{" "}
          <span className="text-muted-foreground font-normal">
            {totalCount != null && `(${totalCount.toLocaleString()} tools)`}
          </span>
        </h1>
        <div className="flex items-center gap-3">
          <Input
            placeholder="Library name"
            value={libraryName}
            onChange={(e) => setLibraryName(e.target.value)}
            className="w-48"
          />
          <Button onClick={handleExport} disabled={cart.size === 0}>
            Export ({cart.size})
          </Button>
        </div>
      </div>

      {cart.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-4 py-2 text-sm">
          <span className="font-medium">{cart.size} tool{cart.size !== 1 ? "s" : ""} in library</span>
          <button
            onClick={() => setCart(new Map())}
            className="ml-2 text-xs text-muted-foreground hover:underline"
          >
            Clear all
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search by description or part number..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <FilterDropdown
          label="All vendors"
          options={vendors}
          selected={vendorFilter}
          onToggle={(v) => toggleFilter(vendorFilter, v, setVendorFilter)}
          onClear={() => setVendorFilter(new Set())}
        />
        <FilterDropdown
          label="All types"
          options={types}
          selected={typeFilter}
          onToggle={(v) => toggleFilter(typeFilter, v, setTypeFilter)}
          onClear={() => setTypeFilter(new Set())}
        />
        {results.length > 0 && (
          <button
            onClick={addAllVisible}
            className="text-xs text-muted-foreground hover:underline"
          >
            Add all visible
          </button>
        )}
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead className="min-w-[200px] max-w-[320px]">Description</TableHead>
              <TableHead className="whitespace-nowrap">Part #</TableHead>
              <TableHead>Vendor</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right whitespace-nowrap">Dia (mm)</TableHead>
              <TableHead className="text-right whitespace-nowrap">OAL (mm)</TableHead>
              <TableHead className="text-right">Flutes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                  Searching...
                </TableCell>
              </TableRow>
            ) : results.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                  {search || vendorFilter.size || typeFilter.size
                    ? "No tools match your search."
                    : "Search the reference catalog to find tools."}
                </TableCell>
              </TableRow>
            ) : (
              results.map((row) => {
                const inCart = cart.has(row.id);
                return (
                  <TableRow
                    key={row.id}
                    className={inCart ? "bg-primary/5" : "cursor-pointer hover:bg-accent/50"}
                    onClick={() => toggleCart(row)}
                  >
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={inCart}
                        onChange={() => toggleCart(row)}
                        className="rounded"
                      />
                    </TableCell>
                    <TableCell className="max-w-[320px]">
                      <span className="block truncate" title={row.description}>
                        {row.description}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-sm">{row.product_id}</TableCell>
                    <TableCell>{row.vendor}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{row.type}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">{fmtMm(row.geo_dc)}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{fmtMm(row.geo_oal)}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{row.geo_nof ?? "\u2014"}</TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => fetchResults(page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages - 1}
              onClick={() => fetchResults(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
