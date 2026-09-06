"use client";

import type { CatalogProduct } from "@/lib/catalog-view";
import { useCart } from "@/components/cart/CartProvider";
import { PLACEHOLDER_IMAGE } from "@/components/product/placeholder";
import { PlusIcon } from "@/components/icons";

/**
 * The only interactive part of a product card, and the only part that needs
 * `useCart`. Splitting it out is what lets `ProductCard` — image, title, price,
 * swatches — render on the server (QA defect D3).
 *
 * Rendered only for products that can actually be added straight from the grid:
 * a card with options sends the shopper to the PDP to choose.
 */
export function QuickAddButton({ product }: { product: CatalogProduct }) {
  const { add, addVariant } = useCart();
  const hasSizes = product.sizes.length > 0;

  const quickAdd = () => {
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
    <button
      type="button"
      onClick={quickAdd}
      aria-label={`Quick add ${product.title} to bag`}
      className="absolute bottom-3 right-3 z-10 flex h-10 items-center gap-1.5 rounded-full bg-paper pl-3 pr-3 text-sm font-semibold text-ink shadow-md transition-all duration-200 hover:bg-ink hover:text-paper focus-visible:translate-y-0 focus-visible:opacity-100 sm:translate-y-2 sm:opacity-0 sm:group-hover:translate-y-0 sm:group-hover:opacity-100"
    >
      <PlusIcon width={16} height={16} aria-hidden="true" />
      <span className="hidden sm:inline">Add</span>
    </button>
  );
}
