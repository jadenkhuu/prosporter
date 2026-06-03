import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { resolveScope, buildFacets, taxonomy } from "@/lib/catalog";
import { Listing } from "@/components/shop/Listing";

type Params = { segments?: string[] };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { segments = [] } = await params;
  const scope = resolveScope(segments);
  if (!scope) return { title: "Not found · ProSporter" };
  return { title: `${scope.title} · ProSporter` };
}

// Pre-render the known category, surface and club listings.
export function generateStaticParams(): Params[] {
  const params: Params[] = [{ segments: [] }];
  for (const cat of taxonomy.primary_nav) params.push({ segments: [cat.id] });
  for (const col of taxonomy.collections) {
    if (col.type === "club") params.push({ segments: ["clubs", col.id] });
    else params.push({ segments: [col.slug] });
  }
  return params;
}

export default async function ShopPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { segments = [] } = await params;
  const scope = resolveScope(segments);
  if (!scope) notFound();

  const facets = buildFacets(scope.products);

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
      {/* Breadcrumb */}
      <nav className="mb-5 flex items-center gap-1.5 text-xs text-subtle" aria-label="Breadcrumb">
        <Link href="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span>/</span>
        <Link href="/shop" className="transition-colors hover:text-ink">
          Shop
        </Link>
        {scope.kind !== "all" && (
          <>
            <span>/</span>
            <span className="text-ink">{scope.title}</span>
          </>
        )}
      </nav>

      {/* Header */}
      <header className="mb-8 max-w-2xl">
        <h1 className="display text-4xl sm:text-5xl">{scope.title}</h1>
        {scope.description && (
          <p className="mt-3 text-base leading-relaxed text-muted">{scope.description}</p>
        )}
      </header>

      {scope.products.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-line bg-surface py-24 text-center">
          <p className="display text-2xl">Nothing here yet</p>
          <p className="max-w-sm text-sm text-muted">
            There are no products in this collection right now. Check back soon.
          </p>
          <Link
            href="/shop"
            className="mt-1 rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper hover:bg-ink-2"
          >
            Shop all
          </Link>
        </div>
      ) : (
        <Listing products={scope.products} facets={facets} />
      )}
    </div>
  );
}
