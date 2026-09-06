import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { getListing, getListingParams } from "@/lib/catalog-source";
import { Listing } from "@/components/shop/Listing";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildBreadcrumbJsonLd } from "@/lib/seo/json-ld";
import { OG_DEFAULTS } from "@/lib/seo/metadata";

type Params = { segments?: string[] };

/** `/shop`, `/shop/beach`, `/shop/clubs/uts` — the path this listing canonicalises to. */
function listingPath(segments: string[]): string {
  return segments.length ? `/shop/${segments.join("/")}` : "/shop";
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { segments = [] } = await params;
  const scope = await getListing(segments);
  if (!scope) return { title: "Not found · ProSporter" };

  const path = listingPath(segments);
  const description =
    scope.description ??
    `Shop ${scope.title.toLowerCase()} at ProSporter — indoor and beach volleyball apparel, club teamwear and protective gear, shipped across Australia.`;
  return {
    title: `${scope.title} · ProSporter`,
    description,
    // Facet and sort state lives in the query string and is applied client-side
    // in Listing.tsx, so every variant of this listing canonicalises to the
    // clean path. robots.txt disallows the `?sort=`/`?filter` permutations too.
    alternates: { canonical: path },
    openGraph: {
      ...OG_DEFAULTS,
      type: "website",
      url: path,
      title: scope.title,
      description,
    },
  };
}

/** Empty when Shopify is unconfigured or unreachable; those routes render on demand. */
export async function generateStaticParams(): Promise<Params[]> {
  return (await getListingParams()).map((segments) => ({ segments }));
}

export default async function ShopPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { segments = [] } = await params;
  const scope = await getListing(segments);
  if (!scope) notFound();

  // Mirrors the visible breadcrumb below, which is what BreadcrumbList must do.
  const crumbs = [
    { name: "Home", path: "/" },
    { name: "Shop", path: "/shop" },
    ...(scope.kind === "all" ? [] : [{ name: scope.title, path: listingPath(segments) }]),
  ];

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
      <JsonLd data={buildBreadcrumbJsonLd(crumbs)} />
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
        <Listing products={scope.products} facets={scope.facets} />
      )}
    </div>
  );
}
