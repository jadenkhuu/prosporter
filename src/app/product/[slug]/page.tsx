import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";
import { catalog, getProductBySlug, getCategoryLabel } from "@/lib/catalog";
import { ProductDetail } from "@/components/product/ProductDetail";
import { ProductCard } from "@/components/product/ProductCard";

export function generateStaticParams() {
  return catalog.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const product = getProductBySlug(slug);
  if (!product) return { title: "Not found · ProSporter" };
  return { title: `${product.name} · ProSporter` };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const product = getProductBySlug(slug);
  if (!product) notFound();

  // Related: same category, then pad with same club, excluding this item.
  const sameCategory = catalog.filter(
    (p) => p.primary_category === product.primary_category && p.slug !== product.slug,
  );
  const sameClub = catalog.filter(
    (p) =>
      p.slug !== product.slug &&
      p.primary_category !== product.primary_category &&
      p.clubs.some((c) => product.clubs.includes(c)),
  );
  const related = [...sameCategory, ...sameClub].slice(0, 4);

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
      <nav className="mb-6 flex items-center gap-1.5 text-xs text-subtle" aria-label="Breadcrumb">
        <Link href="/" className="transition-colors hover:text-ink">
          Home
        </Link>
        <span>/</span>
        <Link
          href={`/shop/${product.primary_category}`}
          className="transition-colors hover:text-ink"
        >
          {getCategoryLabel(product.primary_category)}
        </Link>
        <span>/</span>
        <span className="line-clamp-1 text-ink">{product.name}</span>
      </nav>

      <ProductDetail product={product} />

      {related.length > 0 && (
        <section className="mt-20">
          <h2 className="display mb-6 text-2xl sm:text-3xl">You might also like</h2>
          <div className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-4">
            {related.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
