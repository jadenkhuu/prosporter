import Link from "next/link";
import Image from "next/image";
import type { CatalogProduct } from "@/lib/catalog-view";
import { formatPriceRange, swatchFor } from "@/lib/format";
import { PLACEHOLDER_IMAGE } from "@/components/product/placeholder";
import { QuickAddButton } from "@/components/product/QuickAddButton";

/**
 * Server component. The card is static markup — image, badges, title, price,
 * swatches — and only the quick-add button needs the cart, so that one control
 * is the client island (`QuickAddButton`). Grids of these are what the LCP
 * element usually is on a collection page (QA defect D3).
 */
export function ProductCard({
  product,
  priority = false,
}: {
  product: CatalogProduct;
  priority?: boolean;
}) {
  const hasSizes = product.sizes.length > 0;
  // Only single-variant products can be added straight from the grid; anything
  // with options sends the shopper to the PDP to choose.
  const canQuickAdd = product.inStock && (product.variantId !== null || !hasSizes);

  // One tab stop per card: the title link stretches over the whole card with a
  // pseudo-element, so the image is not a second link and the quick-add button
  // (raised above the overlay) stays independently reachable.
  return (
    <div className="group relative">
      <div className="relative aspect-[4/5] overflow-hidden rounded-card bg-surface">
        <Image
          src={product.image?.url ?? PLACEHOLDER_IMAGE}
          alt=""
          fill
          unoptimized={!product.image}
          sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
          priority={priority}
          className="object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]"
        />

        {/* Badges */}
        <div className="absolute left-3 top-3 flex flex-col gap-1.5">
          {product.onSale && (
            <span className="rounded-full bg-green-deep px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-paper">
              Sale
            </span>
          )}
          {product.surface === "beach" && (
            <span className="rounded-full bg-paper/90 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-ink">
              Beach
            </span>
          )}
        </div>

        {!product.inStock && (
          <div className="absolute inset-0 grid place-items-center bg-paper/60">
            <span className="eyebrow rounded-full bg-ink px-3 py-1.5 text-paper">
              Sold out
            </span>
          </div>
        )}

        {/* Quick add — appears on hover (desktop), always tappable on touch */}
        {canQuickAdd && <QuickAddButton product={product} />}
      </div>

      <div className="mt-3">
        <p className="eyebrow text-subtle">{product.categoryLabel}</p>
        <h3 className="mt-1 text-sm font-medium text-ink">
          {/* The clamp lives on an inner span: an `overflow:hidden` ancestor
              would clip the stretched ::after overlay. */}
          <Link
            href={`/product/${product.handle}`}
            className="after:absolute after:inset-0 after:rounded-card after:content-[''] focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-green-deep"
          >
            <span className="line-clamp-1">{product.title}</span>
          </Link>
        </h3>
        <div className="mt-1.5 flex items-center justify-between">
          <p className="text-sm font-semibold tabular-nums">
            {formatPriceRange(product.price, product.maxPrice, product.currency)}
          </p>
          {product.colours.length > 0 && (
            <div className="flex items-center gap-1">
              {product.colours.slice(0, 4).map((c) => (
                <span
                  key={c}
                  title={c}
                  aria-hidden="true"
                  className="h-3 w-3 rounded-full ring-1 ring-line ring-inset"
                  style={{ background: swatchFor(c) }}
                />
              ))}
              {product.colours.length > 4 && (
                <span aria-hidden="true" className="text-[10px] text-subtle">
                  +{product.colours.length - 4}
                </span>
              )}
              <span className="sr-only">
                {product.colours.length === 1
                  ? "1 colour available"
                  : `${product.colours.length} colours available`}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
