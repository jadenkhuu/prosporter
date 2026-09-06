"use client";

import { useCallback, useId, useRef, useState } from "react";
import { useCart } from "./CartProvider";
import { formatPrice } from "@/lib/format";
import { normalizeDiscountCode } from "@/lib/cart-totals";
import { useModalDialog } from "@/lib/hooks/useModalDialog";
import { CloseIcon, PlusIcon, MinusIcon, ArrowRight, ChevronDown } from "@/components/icons";
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

/**
 * "Have a discount code?" — a disclosure over a one-field form, plus a chip per
 * applied code.
 *
 * Accessibility notes:
 *  - the toggle is a real <button> with aria-expanded / aria-controls, so
 *    Tab + Enter/Space work with no key handling of our own;
 *  - the panel is hidden with `hidden` rather than unmounted, which keeps the
 *    drawer's focus trap (it skips controls with no layout box) correct;
 *  - the input is labelled, marked aria-invalid on failure and described by the
 *    message node;
 *  - one polite live region carries either the failure or the confirmation, and
 *    the visible copy is aria-hidden so it is not read twice.
 */
function DiscountCode() {
  const { applyDiscount, discountCodes, isPending, error, errorSource } = useCart();
  const uid = useId();
  const panelId = `discount-panel-${uid}`;
  const inputId = `discount-input-${uid}`;
  const messageId = `discount-message-${uid}`;

  const [expanded, setExpanded] = useState(false);
  const [code, setCode] = useState("");

  const discountError = error && errorSource === "discount" ? error : null;

  const submit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const next = normalizeDiscountCode(code);
      if (!next || isPending) return;
      applyDiscount(next);
      setCode("");
    },
    [applyDiscount, code, isPending],
  );

  const announcement = discountError
    ? discountError
    : discountCodes.length
      ? `Discount code ${discountCodes.join(", ")} applied.`
      : "";

  return (
    <div className="mb-4 border-b border-line pb-4">
      {discountCodes.length > 0 && (
        <ul className="mb-3 flex flex-wrap gap-2" aria-label="Applied discount codes">
          {discountCodes.map((applied) => (
            <li key={applied}>
              <span className="inline-flex items-center gap-1 rounded-full border border-green-deep bg-surface py-1 pl-3 pr-1 text-xs font-semibold text-green-deep">
                <span aria-hidden="true">{applied}</span>
                <button
                  type="button"
                  onClick={() => applyDiscount("")}
                  disabled={isPending}
                  aria-disabled={isPending}
                  aria-label={`Remove discount code ${applied}`}
                  className="grid h-6 w-6 place-items-center rounded-full text-green-deep transition-colors hover:bg-surface-2 disabled:opacity-50"
                >
                  <CloseIcon width={14} height={14} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-center justify-between gap-2 py-1 text-sm font-medium text-ink"
      >
        Have a discount code?
        <ChevronDown
          width={16}
          height={16}
          aria-hidden="true"
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      <div id={panelId} hidden={!expanded} className="mt-2">
        <form onSubmit={submit} className="flex gap-2">
          <label className="sr-only" htmlFor={inputId}>
            Discount code
          </label>
          <input
            id={inputId}
            name="discountCode"
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="Enter code"
            aria-invalid={discountError ? true : undefined}
            aria-describedby={messageId}
            className="min-w-0 flex-1 rounded-full border border-line bg-paper px-4 py-2.5 text-sm text-ink placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={isPending || normalizeDiscountCode(code).length === 0}
            aria-disabled={isPending || normalizeDiscountCode(code).length === 0}
            aria-busy={isPending}
            className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2 disabled:opacity-50"
          >
            {isPending ? "Applying…" : "Apply"}
          </button>
        </form>
        {discountError && (
          <p className="mt-2 text-xs text-ink" aria-hidden="true">
            {discountError}
          </p>
        )}
      </div>

      <p id={messageId} className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}

export function CartDrawer() {
  const {
    lines,
    isOpen,
    close,
    subtotal,
    discount,
    total,
    currencyCode,
    count,
    setQty,
    remove,
    checkoutUrl,
    enabled,
    isPending,
    error,
    errorSource,
  } = useCart();

  const panelRef = useRef<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  /**
   * Modal behaviour (focus in, Tab trap, Escape, scroll lock, inert background,
   * focus back to the opener) is shared with the mobile menu and the filter
   * sheet. See src/lib/hooks/useModalDialog.ts.
   */
  useModalDialog({
    open: isOpen,
    panelRef,
    rootRef,
    onClose: close,
    inertSiblings: true,
  });

  // Discount failures are shown (and announced) by the discount form itself.
  const cartError = error && errorSource !== "discount" ? error : null;

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
          {cartError ? cartError : bagStatus}
        </p>

        {cartError && (
          <p
            className="border-b border-line bg-surface px-5 py-3 text-sm text-ink"
            aria-hidden="true"
          >
            {cartError}
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
              <DiscountCode />
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted">Subtotal</span>
                <span
                  className={`tabular-nums ${discount > 0 ? "text-sm text-ink" : "display text-xl"}`}
                >
                  {formatPrice(subtotal, currencyCode)}
                </span>
              </div>
              {discount > 0 && (
                <>
                  <div className="mt-1 flex items-center justify-between text-sm text-green-deep">
                    <span>Discount</span>
                    <span className="tabular-nums">
                      <span className="sr-only">minus </span>
                      <span aria-hidden="true">−</span>
                      {formatPrice(discount, currencyCode)}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
                    <span className="text-sm text-muted">Total</span>
                    <span className="display text-xl tabular-nums">
                      {formatPrice(total, currencyCode)}
                    </span>
                  </div>
                </>
              )}
              <p className="mt-1 text-xs text-muted">
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
