"use client";

import { useMemo, useState } from "react";
import type { Product, Facets } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { Filters, emptyFilters, type FilterState } from "./Filters";
import { FilterIcon, CloseIcon, ChevronDown } from "@/components/icons";

const SORTS = [
  { id: "featured", label: "Featured" },
  { id: "price-asc", label: "Price: Low to High" },
  { id: "price-desc", label: "Price: High to Low" },
  { id: "newest", label: "Newest" },
  { id: "name-asc", label: "Name: A–Z" },
] as const;

type SortId = (typeof SORTS)[number]["id"];

const GENDER_LABELS: Record<string, string> = { men: "Men", women: "Women", unisex: "Unisex" };
const SURFACE_LABELS: Record<string, string> = { beach: "Beach", indoor: "Indoor" };

export function Listing({ products, facets }: { products: Product[]; facets: Facets }) {
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const [sort, setSort] = useState<SortId>("featured");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  const filtered = useMemo(() => {
    const result = products.filter((p) => {
      if (filters.inStock && !p.in_stock) return false;
      if (filters.onSale && !p.on_sale) return false;
      if (filters.gender.length && !filters.gender.some((g) => p.gender.includes(g)))
        return false;
      if (filters.surface.length && !(p.surface && filters.surface.includes(p.surface)))
        return false;
      if (filters.colour.length && !filters.colour.some((c) => p.colours.includes(c)))
        return false;
      if (filters.size.length && !filters.size.some((s) => p.sizes.includes(s)))
        return false;
      if (filters.maxPrice != null && p.price > filters.maxPrice) return false;
      return true;
    });

    switch (sort) {
      case "price-asc":
        return [...result].sort((a, b) => a.price - b.price);
      case "price-desc":
        return [...result].sort((a, b) => b.price - a.price);
      case "newest":
        return [...result].sort((a, b) => b.id - a.id);
      case "name-asc":
        return [...result].sort((a, b) => a.name.localeCompare(b.name));
      default:
        return result;
    }
  }, [products, filters, sort]);

  // Active filter chips
  const chips: { label: string; clear: () => void }[] = [];
  filters.gender.forEach((g) =>
    chips.push({
      label: GENDER_LABELS[g] ?? g,
      clear: () => setFilters((f) => ({ ...f, gender: f.gender.filter((x) => x !== g) })),
    }),
  );
  filters.surface.forEach((s) =>
    chips.push({
      label: SURFACE_LABELS[s] ?? s,
      clear: () => setFilters((f) => ({ ...f, surface: f.surface.filter((x) => x !== s) })),
    }),
  );
  filters.colour.forEach((c) =>
    chips.push({
      label: c,
      clear: () => setFilters((f) => ({ ...f, colour: f.colour.filter((x) => x !== c) })),
    }),
  );
  filters.size.forEach((s) =>
    chips.push({
      label: `Size ${s}`,
      clear: () => setFilters((f) => ({ ...f, size: f.size.filter((x) => x !== s) })),
    }),
  );
  if (filters.inStock)
    chips.push({ label: "In stock", clear: () => setFilters((f) => ({ ...f, inStock: false })) });
  if (filters.onSale)
    chips.push({ label: "On sale", clear: () => setFilters((f) => ({ ...f, onSale: false })) });
  if (filters.maxPrice != null)
    chips.push({
      label: `Under $${filters.maxPrice}`,
      clear: () => setFilters((f) => ({ ...f, maxPrice: null })),
    });

  return (
    <div className="lg:grid lg:grid-cols-[260px_1fr] lg:gap-10">
      {/* Desktop sidebar */}
      <aside className="hidden lg:block">
        <div className="sticky top-28">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="eyebrow text-ink">Filters</h2>
            {chips.length > 0 && (
              <button
                onClick={() => setFilters(emptyFilters)}
                className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
              >
                Clear all
              </button>
            )}
          </div>
          <Filters facets={facets} value={filters} onChange={setFilters} />
        </div>
      </aside>

      <section>
        {/* Toolbar */}
        <div className="flex items-center justify-between gap-3 border-b border-line pb-4">
          <p className="text-sm text-muted">
            <span className="font-semibold text-ink tabular-nums">{filtered.length}</span>{" "}
            {filtered.length === 1 ? "product" : "products"}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setMobileFiltersOpen(true)}
              className="flex items-center gap-1.5 rounded-full border border-line px-3.5 py-2 text-sm font-medium lg:hidden"
            >
              <FilterIcon width={16} height={16} />
              Filters
              {chips.length > 0 && (
                <span className="grid h-5 w-5 place-items-center rounded-full bg-ink text-[11px] text-paper">
                  {chips.length}
                </span>
              )}
            </button>
            <div className="relative">
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortId)}
                aria-label="Sort products"
                className="appearance-none rounded-full border border-line bg-paper py-2 pl-3.5 pr-9 text-sm font-medium text-ink"
              >
                {SORTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                width={16}
                height={16}
                className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
              />
            </div>
          </div>
        </div>

        {/* Active chips */}
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-4">
            {chips.map((chip, i) => (
              <button
                key={i}
                onClick={chip.clear}
                className="flex items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-surface-2"
              >
                {chip.label}
                <CloseIcon width={12} height={12} className="text-muted" />
              </button>
            ))}
          </div>
        )}

        {/* Grid */}
        {filtered.length > 0 ? (
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 pt-6 md:grid-cols-3 xl:grid-cols-4">
            {filtered.map((p, i) => (
              <ProductCard key={p.id} product={p} priority={i < 4} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <p className="display text-2xl">No matches</p>
            <p className="max-w-sm text-sm text-muted">
              Nothing fits those filters. Try removing one to see more gear.
            </p>
            <button
              onClick={() => setFilters(emptyFilters)}
              className="mt-1 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper hover:bg-ink-2"
            >
              Clear filters
            </button>
          </div>
        )}
      </section>

      {/* Mobile filter sheet */}
      <div
        className={`fixed inset-0 z-[80] lg:hidden ${
          mobileFiltersOpen ? "" : "pointer-events-none"
        }`}
        aria-hidden={!mobileFiltersOpen}
      >
        <div
          onClick={() => setMobileFiltersOpen(false)}
          className={`absolute inset-0 bg-ink/50 transition-opacity ${
            mobileFiltersOpen ? "opacity-100" : "opacity-0"
          }`}
        />
        <div
          className={`absolute bottom-0 left-0 right-0 flex max-h-[85vh] flex-col rounded-t-2xl bg-paper transition-transform duration-300 ${
            mobileFiltersOpen ? "translate-y-0" : "translate-y-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <h2 className="display text-lg">Filters</h2>
            <button
              onClick={() => setMobileFiltersOpen(false)}
              aria-label="Close filters"
              className="-mr-2 grid h-10 w-10 place-items-center rounded-full hover:bg-surface"
            >
              <CloseIcon />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-5">
            <Filters facets={facets} value={filters} onChange={setFilters} />
          </div>
          <div className="flex gap-3 border-t border-line px-5 py-4">
            <button
              onClick={() => setFilters(emptyFilters)}
              className="flex-1 rounded-full border border-line py-3 text-sm font-semibold"
            >
              Clear all
            </button>
            <button
              onClick={() => setMobileFiltersOpen(false)}
              className="flex-1 rounded-full bg-ink py-3 text-sm font-semibold text-paper"
            >
              Show {filtered.length} results
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
