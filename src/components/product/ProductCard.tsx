"use client";

import Link from "next/link";
import Image from "next/image";
import type { CatalogProduct } from "@/lib/catalog-view";
import { formatPriceRange, swatchFor } from "@/lib/format";
import { useCart } from "@/components/cart/CartProvider";
import { PlusIcon } from "@/components/icons";

/** Shown when a product has no image yet (mid-migration drafts). */
export const PLACEHOLDER_IMAGE = "/products/ace-unisex.png";

export function ProductCard({
  product,
  priority = false,
}: {
  product: CatalogProduct;
  priority?: boolean;
}) {
  const { add, addVariant } = useCart();
  const hasSizes = product.sizes.length > 0;
  // Only single-variant products can be added straight from the grid; anything
  // with options sends the shopper to the PDP to choose.
  const canQuickAdd = product.inStock && (product.variantId !== null || !hasSizes);

  const quickAdd = (e: React.MouseEvent) => {
    e.preventDefault();
    if (product.variantId) {
      addVariant(product.variantId);
      return;
    }
    add({
      slug: product.handle,
      name: product.title,
      price: product.price,
      image: product.image?.url ?? PLACEHOLDER_IMAGE,
      // Quick-add picks the middle size as a default; PDP lets you choose.
      size: hasSizes ? product.sizes[Math.floor(product.sizes.length / 2)] : null,
    });
  };

  return (
    <Link href={`/product/${product.handle}`} className="group block">
      <div className="relative aspect-[4/5] overflow-hidden rounded-card bg-surface">
        <Image
          src={product.image?.url ?? PLACEHOLDER_IMAGE}
          alt={product.image?.alt ?? product.title}
          fill
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
        {canQuickAdd && (
          <button
            onClick={quickAdd}
            aria-label={`Quick add ${product.title}`}
            className="absolute bottom-3 right-3 flex h-10 items-center gap-1.5 rounded-full bg-paper pl-3 pr-3 text-sm font-semibold text-ink shadow-md transition-all duration-200 hover:bg-ink hover:text-paper focus-visible:opacity-100 sm:translate-y-2 sm:opacity-0 sm:group-hover:translate-y-0 sm:group-hover:opacity-100"
          >
            <PlusIcon width={16} height={16} />
            <span className="hidden sm:inline">Add</span>
          </button>
        )}
      </div>

      <div className="mt-3">
        <p className="eyebrow text-subtle">{product.categoryLabel}</p>
        <h3 className="mt-1 line-clamp-1 text-sm font-medium text-ink">{product.title}</h3>
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
                  className="h-3 w-3 rounded-full ring-1 ring-line ring-inset"
                  style={{ background: swatchFor(c) }}
                />
              ))}
              {product.colours.length > 4 && (
                <span className="text-[10px] text-subtle">+{product.colours.length - 4}</span>
              )}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
