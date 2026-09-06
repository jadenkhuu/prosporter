"use client";

import {
  createContext,
  startTransition as reactStartTransition,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useOptimistic,
  useRef,
  useState,
  useTransition,
} from "react";
import type { Cart, CartLine } from "@/lib/shopify/types";
import { nodes } from "@/lib/shopify/types";
import { appliedDiscountCodes, cartDiscountAmount, cartTotals } from "@/lib/cart-totals";
import {
  addToCart,
  applyDiscountCode as applyDiscountCodeAction,
  getCurrentCart,
  removeLine as removeLineAction,
  updateLine as updateLineAction,
} from "@/lib/shopify/cart-actions";

/**
 * Cart state backed by the Shopify Storefront Cart API (CLNT-171).
 *
 * The server owns the cart: `initialCart` is fetched in the root layout from
 * the httpOnly `prosporter_cart` cookie, and every mutation returns the whole
 * cart, which replaces local state. `useOptimistic` covers the round trip so
 * +/- and Remove feel instant.
 *
 * Fallback: when Shopify is not configured (`enabled === false`, CI builds with
 * SHOPIFY_OPTIONAL=1) the provider holds a permanently empty cart and the
 * drawer renders an "unavailable" state. That is simpler and more honest than
 * keeping a second localStorage cart that could never reach checkout.
 */

/** Which UI surface owns the current error message. */
export type CartErrorSource = "cart" | "discount";

type CartError = { message: string; source: CartErrorSource };

type OptimisticAction =
  | { type: "setQuantity"; lineId: string; quantity: number }
  | { type: "remove"; lineId: string };

const money = (amount: string | number, currencyCode: string) => ({
  amount: (typeof amount === "number" ? amount : Number(amount) || 0).toFixed(2),
  currencyCode,
});

/** Recompute totals locally so the optimistic frame is not visibly wrong. */
function recost(cart: Cart, lines: CartLine[]): Cart {
  const currency = cart.cost.subtotalAmount.currencyCode;
  const subtotal = lines.reduce((sum, l) => sum + (Number(l.cost.totalAmount.amount) || 0), 0);
  const taxes = Number(cart.cost.totalTaxAmount?.amount ?? 0) || 0;
  // The optimistic frame keeps whatever discount Shopify last allocated; the
  // real allocation comes back with the action's cart a moment later.
  const discount = cartDiscountAmount(cart);
  return {
    ...cart,
    totalQuantity: lines.reduce((n, l) => n + l.quantity, 0),
    cost: {
      ...cart.cost,
      subtotalAmount: money(subtotal, currency),
      totalAmount: money(
        Math.max(0, subtotal + taxes - discount),
        cart.cost.totalAmount.currencyCode,
      ),
    },
    lines: {
      ...cart.lines,
      edges: lines.map((node, i) => ({ cursor: cart.lines.edges[i]?.cursor ?? node.id, node })),
    },
  };
}

function optimisticReducer(cart: Cart | null, action: OptimisticAction): Cart | null {
  if (!cart) return cart;
  const current = nodes(cart.lines);
  if (action.type === "remove") {
    return recost(cart, current.filter((l) => l.id !== action.lineId));
  }
  const next = current
    .map((l) => {
      if (l.id !== action.lineId) return l;
      const quantity = Math.max(0, action.quantity);
      const unit = Number(l.cost.amountPerQuantity.amount) || 0;
      return {
        ...l,
        quantity,
        cost: { ...l.cost, totalAmount: money(unit * quantity, l.cost.totalAmount.currencyCode) },
      };
    })
    .filter((l) => l.quantity > 0);
  return recost(cart, next);
}

/**
 * Legacy shape used by the pre-Shopify mock catalog. ProductCard/ProductDetail
 * still call `add()` with it while the catalog slice migrates to Shopify types;
 * the shim only opens the drawer. Replace those call sites with
 * <AddToCartButton variantId=… /> and this member goes away.
 */
export type LegacyAddPayload = {
  slug: string;
  name: string;
  price: number;
  image: string;
  size: string | null;
  qty?: number;
};

type CartContextValue = {
  /** Optimistic cart: what the UI should render right now. */
  cart: Cart | null;
  lines: CartLine[];
  count: number;
  /** Subtotal as a number in the cart currency, for `formatPrice`. */
  subtotal: number;
  /** Cart-level discount, positive, 0 when none is applied. */
  discount: number;
  /** What the shopper pays once the discount is applied. */
  total: number;
  /** Discount codes Shopify accepted for this cart. */
  discountCodes: string[];
  currencyCode: string;
  checkoutUrl: string | null;
  /** False when Shopify is not configured. */
  enabled: boolean;
  isOpen: boolean;
  isPending: boolean;
  error: string | null;
  /**
   * Which control should render `error`. The discount form shows its own
   * failures inline; everything else goes to the drawer's error banner.
   */
  errorSource: CartErrorSource;
  open: () => void;
  close: () => void;
  dismissError: () => void;
  addVariant: (variantId: string, quantity?: number) => void;
  setQty: (lineId: string, quantity: number) => void;
  remove: (lineId: string) => void;
  applyDiscount: (code: string) => void;
  refresh: () => void;
  /** @deprecated mock-catalog shim; use AddToCartButton. */
  add: (line: LegacyAddPayload) => void;
};

const Ctx = createContext<CartContextValue | null>(null);

export function CartProvider({
  children,
  initialCart = null,
  enabled = true,
}: {
  children: React.ReactNode;
  initialCart?: Cart | null;
  enabled?: boolean;
}) {
  // Server truth is fetched once after mount (the layout stays static). Every
  // later change comes back from a server action's return value.
  const [cart, setCart] = useState<Cart | null>(initialCart);
  const [optimisticCart, applyOptimistic] = useOptimistic(cart, optimisticReducer);
  const [isOpen, setOpen] = useState(false);
  // One error slot, tagged with the surface that should render it, so the
  // discount form can show its own failure inline without a second state.
  const [error, setError] = useState<CartError | null>(null);
  const [isPending, startTransition] = useTransition();

  const run = useCallback(
    (
      work: () => Promise<{ cart: Cart | null; error: string | null }>,
      options: { optimistic?: OptimisticAction; source?: CartErrorSource } = {},
    ) => {
      startTransition(async () => {
        if (options.optimistic) applyOptimistic(options.optimistic);
        const result = await work();
        reactStartTransition(() => {
          setCart(result.cart);
          setError(result.error ? { message: result.error, source: options.source ?? "cart" } : null);
        });
      });
    },
    [applyOptimistic],
  );

  const fetchedOnMount = useRef(false);
  useEffect(() => {
    if (!enabled || initialCart || fetchedOnMount.current) return;
    fetchedOnMount.current = true;
    // Async: state is set when the action resolves, never synchronously in the effect.
    run(async () => ({ cart: await getCurrentCart(), error: null }));
  }, [enabled, initialCart, run]);

  const value = useMemo<CartContextValue>(() => {
    const lines = nodes(optimisticCart?.lines);
    const totals = cartTotals(optimisticCart);
    return {
      cart: optimisticCart,
      lines,
      count: optimisticCart?.totalQuantity ?? 0,
      subtotal: totals.subtotal,
      discount: totals.discount,
      total: totals.total,
      discountCodes: appliedDiscountCodes(optimisticCart),
      currencyCode: totals.currencyCode,
      checkoutUrl: optimisticCart?.checkoutUrl ?? null,
      enabled,
      isOpen,
      isPending,
      error: error?.message ?? null,
      errorSource: error?.source ?? "cart",
      open: () => setOpen(true),
      close: () => setOpen(false),
      dismissError: () => setError(null),
      addVariant: (variantId, quantity = 1) => {
        setOpen(true);
        run(() => addToCart(variantId, quantity));
      },
      setQty: (lineId, quantity) =>
        run(() => updateLineAction(lineId, quantity), {
          optimistic: { type: "setQuantity", lineId, quantity },
        }),
      remove: (lineId) =>
        run(() => removeLineAction(lineId), { optimistic: { type: "remove", lineId } }),
      applyDiscount: (code) =>
        run(() => applyDiscountCodeAction(code), { source: "discount" }),
      refresh: () =>
        run(async () => ({ cart: await getCurrentCart(), error: null })),
      add: () => setOpen(true),
    };
  }, [optimisticCart, enabled, isOpen, isPending, error, run]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCart() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
