"use client";

import { useEffect } from "react";
import { useCart } from "./CartProvider";
import { formatPrice } from "@/lib/format";
import { CloseIcon, PlusIcon, MinusIcon, ArrowRight } from "@/components/icons";
import type { CartLine } from "@/lib/shopify/types";

const FREE_SHIP_THRESHOLD = 150;

/** Size / colour chosen on the variant, minus Shopify's single-variant default. */
function variantSummary(line: CartLine): string | null {
  const parts = line.merchandise.selectedOptions
    .filter((o) => o.value && o.value !== "Default Title")
    .map((o) => o.value);
  return parts.length ? parts.join(" · ") : null;
}

function lineImage(line: CartLine) {
  return line.merchandise.image ?? line.merchandise.product.featuredImage;
}

export function CartDrawer() {
  const {
    lines,
    isOpen,
    close,
    subtotal,
    currencyCode,
    count,
    setQty,
    remove,
    checkoutUrl,
    enabled,
    isPending,
    error,
  } = useCart();

  // Lock body scroll while the drawer is open.
  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [isOpen, close]);

  const remaining = Math.max(0, FREE_SHIP_THRESHOLD - subtotal);
  const progress = Math.min(100, (subtotal / FREE_SHIP_THRESHOLD) * 100);

  return (
    <div
      className={`fixed inset-0 z-[100] ${isOpen ? "" : "pointer-events-none"}`}
      aria-hidden={!isOpen}
    >
      {/* Scrim */}
      <div
        onClick={close}
        className={`absolute inset-0 bg-ink/50 transition-opacity duration-300 ${
          isOpen ? "opacity-100" : "opacity-0"
        }`}
      />

      {/* Panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Shopping bag"
        className={`absolute right-0 top-0 flex h-full w-full max-w-[420px] flex-col bg-paper shadow-2xl transition-transform duration-300 ease-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="display text-lg">
            Your Bag{" "}
            <span className="font-sans text-sm font-medium text-muted normal-case">
              ({count})
            </span>
          </h2>
          <button
            onClick={close}
            aria-label="Close bag"
            className="-mr-2 grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
          >
            <CloseIcon />
          </button>
        </header>

        {error && (
          <p role="status" className="border-b border-line bg-surface px-5 py-3 text-sm text-ink">
            {error}
          </p>
        )}

        {!enabled ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <p className="display text-2xl text-ink">Bag unavailable</p>
            <p className="text-sm text-muted">
              Online ordering is offline for a moment. Please try again shortly.
            </p>
            <button
              onClick={close}
              className="mt-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
            >
              Continue shopping
            </button>
          </div>
        ) : lines.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <p className="display text-2xl text-ink">Your bag is empty</p>
            <p className="text-sm text-muted">
              Add some gear and it’ll show up here.
            </p>
            <button
              onClick={close}
              className="mt-2 rounded-full bg-ink px-6 py-3 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
            >
              Continue shopping
            </button>
          </div>
        ) : (
          <>
            {/* Free shipping progress */}
            {remaining > 0 && (
              <div className="border-b border-line px-5 py-3">
                <p className="text-xs text-muted">
                  You’re{" "}
                  <span className="font-semibold text-ink">
                    {formatPrice(remaining, currencyCode)}
                  </span>{" "}
                  away from free shipping
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-green-deep transition-[width] duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            <ul
              className={`flex-1 divide-y divide-line overflow-y-auto px-5 transition-opacity ${
                isPending ? "opacity-60" : ""
              }`}
            >
              {lines.map((line) => {
                const image = lineImage(line);
                const summary = variantSummary(line);
                return (
                  <li key={line.id} className="flex gap-4 py-4">
                    <div className="relative h-24 w-20 shrink-0 overflow-hidden rounded-card bg-surface">
                      {image && (
                        // Plain <img>: cdn.shopify.com is not in next.config.ts
                        // images.remotePatterns and that file is owned elsewhere.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={image.url}
                          alt={image.altText ?? line.merchandise.product.title}
                          width={80}
                          height={96}
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      )}
                    </div>
                    <div className="flex flex-1 flex-col">
                      <div className="flex justify-between gap-2">
                        <p className="text-sm font-medium leading-snug text-ink">
                          {line.merchandise.product.title}
                        </p>
                        <p className="whitespace-nowrap text-sm font-semibold tabular-nums">
                          {formatPrice(
                            Number(line.cost.totalAmount.amount) || 0,
                            line.cost.totalAmount.currencyCode,
                          )}
                        </p>
                      </div>
                      {summary && <p className="mt-0.5 text-xs text-muted">{summary}</p>}
                      {!line.merchandise.availableForSale && (
                        <p className="mt-0.5 text-xs text-subtle">Out of stock</p>
                      )}
                      <div className="mt-auto flex items-center justify-between pt-2">
                        <div className="flex items-center rounded-full border border-line">
                          <button
                            onClick={() => setQty(line.id, line.quantity - 1)}
                            disabled={isPending}
                            aria-label="Decrease quantity"
                            className="grid h-8 w-8 place-items-center text-ink transition-colors hover:text-green-deep disabled:opacity-50"
                          >
                            <MinusIcon width={16} height={16} />
                          </button>
                          <span className="w-6 text-center text-sm tabular-nums">
                            {line.quantity}
                          </span>
                          <button
                            onClick={() => setQty(line.id, line.quantity + 1)}
                            disabled={isPending}
                            aria-label="Increase quantity"
                            className="grid h-8 w-8 place-items-center text-ink transition-colors hover:text-green-deep disabled:opacity-50"
                          >
                            <PlusIcon width={16} height={16} />
                          </button>
                        </div>
                        <button
                          onClick={() => remove(line.id)}
                          disabled={isPending}
                          className="text-xs text-subtle underline-offset-2 transition-colors hover:text-ink hover:underline disabled:opacity-50"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

            <footer className="border-t border-line px-5 py-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted">Subtotal</span>
                <span className="display text-xl tabular-nums">
                  {formatPrice(subtotal, currencyCode)}
                </span>
              </div>
              <p className="mt-1 text-xs text-subtle">
                Shipping &amp; taxes calculated at checkout.
              </p>
              {checkoutUrl ? (
                <a
                  href={checkoutUrl}
                  target="_self"
                  rel="nofollow"
                  className="mt-4 flex items-center justify-center gap-2 rounded-full bg-ink px-6 py-3.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
                >
                  Checkout
                  <ArrowRight width={18} height={18} />
                </a>
              ) : (
                <span className="mt-4 flex cursor-not-allowed items-center justify-center gap-2 rounded-full bg-ink/40 px-6 py-3.5 text-sm font-semibold text-paper">
                  Checkout
                </span>
              )}
              <p className="mt-2 text-center text-[11px] text-subtle">
                Secure checkout powered by Shopify
              </p>
            </footer>
          </>
        )}
      </aside>
    </div>
  );
}
