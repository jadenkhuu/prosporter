"use client";

import { useEffect, useRef } from "react";
import { useCart } from "./CartProvider";
import { formatPrice } from "@/lib/format";
import { CloseIcon, PlusIcon, MinusIcon, ArrowRight } from "@/components/icons";
import type { CartLine } from "@/lib/shopify/types";

const FREE_SHIP_THRESHOLD = 150;

/** Everything a shopper can Tab to inside the panel, in DOM order. */
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

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

  const panelRef = useRef<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  /** The control that opened the drawer; focus goes back to it on close. */
  const openerRef = useRef<HTMLElement | null>(null);

  /**
   * Modal behaviour, all in one effect and all imperative — no setState, so
   * `react-hooks/set-state-in-effect` stays happy:
   *  - remember the opener, move focus into the panel
   *  - trap Tab / Shift+Tab inside the panel, close on Escape
   *  - lock body scroll and make every sibling of the drawer `inert`
   *  - on close, undo all of it and return focus to the opener
   */
  useEffect(() => {
    if (!isOpen) return;
    const panel = panelRef.current;
    const root = rootRef.current;
    if (!panel) return;

    openerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Background is inert while the dialog is open (blocks pointer, focus and AT).
    const inerted: HTMLElement[] = [];
    if (root?.parentElement) {
      for (const sibling of Array.from(root.parentElement.children)) {
        if (sibling === root || !(sibling instanceof HTMLElement)) continue;
        if (sibling.hasAttribute("inert")) continue;
        sibling.setAttribute("inert", "");
        inerted.push(sibling);
      }
    }

    // Focus the panel itself so screen readers announce the dialog name first.
    panel.focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === panel,
      );
      if (items.length === 0) {
        e.preventDefault();
        panel.focus({ preventScroll: true });
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (active instanceof HTMLElement && !panel.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);

    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKey, true);
      for (const el of inerted) el.removeAttribute("inert");
      openerRef.current?.focus({ preventScroll: true });
    };
  }, [isOpen, close]);

  const remaining = Math.max(0, FREE_SHIP_THRESHOLD - subtotal);
  const progress = Math.min(100, (subtotal / FREE_SHIP_THRESHOLD) * 100);

  // Announced politely whenever the bag changes while the drawer is open.
  const bagStatus = !enabled
    ? "Bag unavailable"
    : count === 0
      ? "Your bag is empty"
      : `${count} ${count === 1 ? "item" : "items"} in your bag. Subtotal ${formatPrice(
          subtotal,
          currencyCode,
        )}.`;

  return (
    <div
      ref={rootRef}
      className={`fixed inset-0 z-[100] ${isOpen ? "" : "pointer-events-none"}`}
      inert={!isOpen}
    >
      {/* Scrim */}
      <div
        onClick={close}
        aria-hidden="true"
        className={`absolute inset-0 bg-ink/50 transition-opacity duration-300 ${
          isOpen ? "opacity-100" : "opacity-0"
        }`}
      />

      {/* Panel */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cart-drawer-title"
        tabIndex={-1}
        className={`absolute right-0 top-0 flex h-full w-full max-w-[420px] flex-col bg-paper shadow-2xl outline-none transition-transform duration-300 ease-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="display text-lg" id="cart-drawer-title">
            Your Bag{" "}
            <span className="font-sans text-sm font-medium text-muted normal-case">
              ({count})
            </span>
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close bag"
            className="-mr-2 grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
          >
            <CloseIcon />
          </button>
        </header>

        {/* Status + error live region: one node that stays mounted so changes
            are announced rather than re-announcing the whole drawer. */}
        <p className="sr-only" aria-live="polite" role="status">
          {error ? error : bagStatus}
        </p>

        {error && (
          <p
            className="border-b border-line bg-surface px-5 py-3 text-sm text-ink"
            aria-hidden="true"
          >
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
              type="button"
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
              type="button"
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
                <div
                  className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
                  role="progressbar"
                  aria-label="Progress to free shipping"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(progress)}
                >
                  <div
                    className="h-full rounded-full bg-green-deep transition-[width] duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            <ul
              aria-label="Items in your bag"
              aria-busy={isPending}
              className={`flex-1 divide-y divide-line overflow-y-auto px-5 transition-opacity ${
                isPending ? "opacity-60" : ""
              }`}
            >
              {lines.map((line) => {
                const image = lineImage(line);
                const summary = variantSummary(line);
                const title = line.merchandise.product.title;
                const name = summary ? `${title} (${summary})` : title;
                return (
                  <li key={line.id} className="flex gap-4 py-4">
                    <div className="relative h-24 w-20 shrink-0 overflow-hidden rounded-card bg-surface">
                      {image && (
                        // Plain <img>: cdn.shopify.com is not in next.config.ts
                        // images.remotePatterns and that file is owned elsewhere.
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={image.url}
                          alt=""
                          width={80}
                          height={96}
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      )}
                    </div>
                    <div className="flex flex-1 flex-col">
                      <div className="flex justify-between gap-2">
                        <p className="text-sm font-medium leading-snug text-ink">{title}</p>
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
                            type="button"
                            onClick={() => setQty(line.id, line.quantity - 1)}
                            disabled={isPending}
                            aria-disabled={isPending}
                            aria-label={`Decrease quantity of ${name}`}
                            className="grid h-8 w-8 place-items-center text-ink transition-colors hover:text-green-deep disabled:opacity-50"
                          >
                            <MinusIcon width={16} height={16} />
                          </button>
                          <span className="w-6 text-center text-sm tabular-nums">
                            <span className="sr-only">Quantity: </span>
                            {line.quantity}
                          </span>
                          <button
                            type="button"
                            onClick={() => setQty(line.id, line.quantity + 1)}
                            disabled={isPending}
                            aria-disabled={isPending}
                            aria-label={`Increase quantity of ${name}`}
                            className="grid h-8 w-8 place-items-center text-ink transition-colors hover:text-green-deep disabled:opacity-50"
                          >
                            <PlusIcon width={16} height={16} />
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => remove(line.id)}
                          disabled={isPending}
                          aria-disabled={isPending}
                          aria-label={`Remove ${name} from bag`}
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
                  <ArrowRight width={18} height={18} aria-hidden="true" />
                </a>
              ) : (
                <span
                  className="mt-4 flex cursor-not-allowed items-center justify-center gap-2 rounded-full bg-ink/40 px-6 py-3.5 text-sm font-semibold text-paper"
                  role="link"
                  aria-disabled="true"
                >
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
