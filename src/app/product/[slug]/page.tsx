import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { getProductHandles, getProductPage } from "@/lib/catalog-source";
import { ProductDetail } from "@/components/product/ProductDetail";
import { ProductCard } from "@/components/product/ProductCard";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildBreadcrumbJsonLd, buildProductJsonLd } from "@/lib/seo/json-ld";
import { OG_DEFAULTS } from "@/lib/seo/metadata";

/** Empty when Shopify is unconfigured or unreachable; those routes render on demand. */
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return (await getProductHandles()).map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = await getProductPage(slug);
  if (!page) return { title: "Not found · ProSporter" };

  const { product } = page;
  const description = product.seo.description || product.description || undefined;
  return {
    title: product.seo.title || `${product.title} · ProSporter`,
    description,
    alternates: { canonical: `/product/${product.handle}` },
    openGraph: {
      ...OG_DEFAULTS,
      type: "website",
      url: `/product/${product.handle}`,
      title: product.seo.title || product.title,
      description,
      images: product.image ? [{ url: product.image.url }] : undefined,
    },
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const page = await getProductPage(slug);
  if (!page) notFound();

  const { product, related } = page;

  /**
   * Product + BreadcrumbList structured data, built from the same view model
   * the page renders so the two can never disagree. One variant emits a plain
   * Offer with its SKU; several emit an AggregateOffer over the price range the
   * page itself shows.
   */
  const productJsonLd = buildProductJsonLd({
    path: `/product/${product.handle}`,
    name: product.title,
    description: product.seo.description || product.description,
    images: product.images.map((image) => image.url),
    brand: product.vendor,
    sku: product.variants.length === 1 ? product.variants[0].sku : null,
    currency: product.currency,
    offers: product.variants.map((variant) => ({
      sku: variant.sku,
      price: variant.price,
      currency: variant.currency,
      available: variant.available,
    })),
    // The mock catalog has no variants; the card's price range still describes it.
    priceRange: { min: product.price, max: product.maxPrice, available: product.inStock },
  });

  const breadcrumbJsonLd = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: product.breadcrumb.label, path: product.breadcrumb.href },
    { name: product.title, path: `/product/${product.handle}` },
  ]);

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
      <JsonLd data={[productJsonLd, breadcrumbJsonLd]} />
      <nav className="mb-6 flex items-center gap-1.5 text-xs text-subtle" aria-label="Breadcrumb">
        <Link href="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span>/</span>
        <Link href={product.breadcrumb.href} className="transition-colors hover:text-ink">
          {product.breadcrumb.label}
        </Link>
        <span>/</span>
        <span className="line-clamp-1 text-ink">{product.title}</span>
      </nav>

      <ProductDetail product={product} />

      {related.length > 0 && (
        <section className="mt-20">
          <h2 className="display mb-6 text-2xl sm:text-3xl">You might also like</h2>
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-4">
            {related.map((p) => (
              <ProductCard key={p.handle} product={p} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
