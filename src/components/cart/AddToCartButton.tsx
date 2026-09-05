"use client";

import { useCart } from "./CartProvider";

/**
 * Self-contained add-to-bag control (CLNT-171).
 *
 * Drop this into the product page in place of the old `useCart().add(...)`
 * handler: it calls the `addToCart` server action, opens the drawer and shows
 * pending / unavailable states on its own. All it needs is the Shopify variant
 * gid, e.g. `product.variants.edges[0].node.id`.
 */
export function AddToCartButton({
  variantId,
  available,
  quantity = 1,
  className,
  children,
}: {
  variantId: string;
  available: boolean;
  quantity?: number;
  className?: string;
  children?: React.ReactNode;
}) {
  const { addVariant, isPending, enabled } = useCart();
  const disabled = !enabled || !available || !variantId || isPending;

  const label = !enabled
    ? "Unavailable"
    : !available
      ? "Sold out"
      : isPending
        ? "Adding…"
        : (children ?? "Add to bag");

  return (
    <button
      type="button"
      disabled={disabled}
      aria-disabled={disabled}
      onClick={() => addVariant(variantId, quantity)}
      className={
        className ??
        "w-full rounded-full bg-ink px-6 py-4 text-sm font-semibold text-paper transition-colors hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-50"
      }
    >
      {label}
    </button>
  );
}
