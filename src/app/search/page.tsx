import Link from "next/link";
import type { Metadata } from "next";
import { searchCatalog, type SearchSort } from "@/lib/catalog-source";
import { ProductCard } from "@/components/product/ProductCard";
import { SearchIcon } from "@/components/icons";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

const SORTS: { id: SearchSort; label: string }[] = [
  { id: "relevance", label: "Relevance" },
  { id: "price-asc", label: "Price: Low to High" },
  { id: "price-desc", label: "Price: High to Low" },
];

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

function toSort(value: string): SearchSort {
  return SORTS.some((s) => s.id === value) ? (value as SearchSort) : "relevance";
}

/**
 * Search result pages are `noindex, follow`: infinite query permutations are
 * classic thin/duplicate content, but the product links on them should still
 * be crawled.
 */
export async function generateMetadata({
  searchParams,
}: {
  searchParams: SearchParams;
}): Promise<Metadata> {
  const q = first((await searchParams).q).trim();
  return {
    title: q ? `Search: ${q} · ProSporter` : "Search · ProSporter",
    description: "Search the ProSporter range of indoor and beach volleyball gear.",
    // Self canonical on the query, not on bare /search: the sort permutations of
    // one query are the duplicates worth collapsing, and pointing `?q=shorts` at
    // `/search` would canonicalise to a page with different content (QA D8).
    alternates: { canonical: q ? `/search?q=${encodeURIComponent(q)}` : "/search" },
    robots: { index: false, follow: true },
  };
}

export default async function SearchPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const query = first(params.q).trim();
  const sort = toSort(first(params.sort));
  const { products, total } = await searchCatalog(query, sort);

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
      {/* Breadcrumb */}
      <nav className="mb-5 flex items-center gap-1.5 text-xs text-subtle" aria-label="Breadcrumb">
        <Link href="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span>/</span>
        <span className="text-ink">Search</span>
      </nav>

      <header className="mb-8 max-w-2xl">
        <h1 className="display text-4xl sm:text-5xl">
          {query ? <>Results for &ldquo;{query}&rdquo;</> : "Search"}
        </h1>
        {query && (
          <p className="mt-3 text-base text-muted">
            <span className="font-semibold text-ink tabular-nums">{total}</span>{" "}
            {total === 1 ? "product" : "products"} found
          </p>
        )}
      </header>

      {/* Search form — works without JavaScript and re-runs the query. */}
      <form role="search" action="/search" className="mb-8 max-w-xl">
        <label htmlFor="search-page-input" className="eyebrow mb-2 block text-subtle">
          Search products
        </label>
        <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2.5 focus-within:border-ink">
          <SearchIcon className="shrink-0 text-muted" aria-hidden />
          <input
            id="search-page-input"
            type="search"
            name="q"
            defaultValue={query}
            placeholder="Jerseys, shorts, knee pads…"
            autoComplete="off"
            className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-subtle"
          />
          <button
            type="submit"
            className="shrink-0 rounded-full bg-ink px-4 py-1.5 text-sm font-semibold text-paper hover:bg-ink-2"
          >
            Search
          </button>
        </div>
        {sort !== "relevance" && <input type="hidden" name="sort" value={sort} />}
      </form>

      {!query ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-line bg-surface py-24 text-center">
          <p className="display text-2xl">What are you looking for?</p>
          <p className="max-w-sm text-sm text-muted">
            Search by product, club or colour — or browse the full range.
          </p>
          <Link
            href="/shop"
            className="mt-1 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper hover:bg-ink-2"
          >
            Shop all
          </Link>
        </div>
      ) : products.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-line bg-surface py-24 text-center">
          <p className="display text-2xl">No results</p>
          <p className="max-w-sm text-sm text-muted">
            Nothing matched &ldquo;{query}&rdquo;. Try a shorter or more general term, or browse the
            full range.
          </p>
          <Link
            href="/shop"
            className="mt-1 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper hover:bg-ink-2"
          >
            Shop all
          </Link>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-line pb-4">
            <span className="eyebrow mr-1 text-subtle">Sort</span>
            {SORTS.map((s) => (
              <Link
                key={s.id}
                href={`/search?q=${encodeURIComponent(query)}${
                  s.id === "relevance" ? "" : `&sort=${s.id}`
                }`}
                aria-current={s.id === sort ? "true" : undefined}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  s.id === sort
                    ? "bg-ink text-paper"
                    : "bg-surface text-ink hover:bg-surface-2"
                }`}
              >
                {s.label}
              </Link>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 pt-6 md:grid-cols-3 xl:grid-cols-4">
            {products.map((p, i) => (
              <ProductCard key={p.handle} product={p} priority={i < 4} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
