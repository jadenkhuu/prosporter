"use server";

/**
 * Cart server actions (CLNT-171).
 *
 * The Shopify cart id is the only thing we persist: an httpOnly cookie that the
 * browser never reads. Every mutation goes through here, returns the whole cart
 * back to the client, and never throws at the UI — failures come back as a
 * `error` string the drawer can render.
 *
 * Fallback: when `isShopifyConfigured()` is false (CI builds with
 * SHOPIFY_OPTIONAL=1) every action short-circuits to a null cart plus the
 * "unavailable" message, so the app builds and the drawer renders a disabled
 * state instead of crashing. See CartProvider for the UI half.
 */
import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import {
  CartUserError,
  addCartLines,
  createCart,
  getCart,
  isShopifyConfigured,
  isShopifyError,
  removeCartLines,
  updateCartLines,
} from "@/lib/shopify";
// See cart.ts: index.ts's updateCartDiscountCodes is unusable on API 2026-07.
import { updateCartDiscountCodesFixed } from "@/lib/shopify/cart";
import type { Cart } from "@/lib/shopify/types";
import { errorFields, log } from "@/lib/log";

/** Name is public (it ships in Set-Cookie); the value is an opaque Shopify gid. */
const COOKIE_NAME = "prosporter_cart";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days
const MAX_QUANTITY = 100;

const GENERIC_ERROR = "Something went wrong updating your bag. Please try again.";
const UNAVAILABLE_ERROR = "The bag is unavailable right now. Please try again later.";

/** Every action returns the full cart so the client can replace its state wholesale. */
export type CartActionResult = {
  cart: Cart | null;
  error: string | null;
  /** False when Shopify is not configured; the UI renders a disabled bag. */
  enabled: boolean;
};

function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  };
}

async function readCartId(): Promise<string | null> {
  const value = (await cookies()).get(COOKIE_NAME)?.value?.trim();
  return value ? value : null;
}

async function writeCartId(id: string): Promise<void> {
  (await cookies()).set(COOKIE_NAME, id, cookieOptions());
}

async function clearCartId(): Promise<void> {
  try {
    (await cookies()).delete(COOKIE_NAME);
  } catch {
    // Cookies are read-only during render; getCurrentCart tolerates a stale id.
  }
}

/**
 * True when Shopify says the cart id we hold is gone (expired, completed or
 * from another store). The Storefront API reports this as a plain `cart: null`
 * on reads and as a userError / GraphQL error on mutations, so we sniff both.
 */
function looksLikeMissingCart(err: unknown): boolean {
  if (err instanceof CartUserError) {
    // Match on the field path, not the message: a bad merchandise id also says
    // "does not exist" and must never delete a live cart. Shopify blames
    // `cartId` only when the cart itself is gone.
    return err.errors.some((e) => e.field?.some((f) => f === "cartId" || f === "id"));
  }
  if (isShopifyError(err) && err.code === "GRAPHQL") {
    return /cart .*(does not exist|not found)|invalid (global )?id/i.test(err.message);
  }
  return false;
}

/** Turn a Shopify CartUserError into one sentence a shopper can act on. */
function friendlyUserError(err: CartUserError): string {
  const first = err.errors[0];
  if (!first) return GENERIC_ERROR;
  switch (first.code) {
    case "INVALID_MERCHANDISE_LINE":
      return "That item is no longer available.";
    case "MISSING_DISCOUNT_CODE":
      return "Enter a discount code first.";
    case "LESS_THAN":
      return "Quantity must be at least 1.";
    case "VALIDATION_CUSTOM":
      return first.message || GENERIC_ERROR;
    case "INVALID":
      // Covers a bad merchandise id, an expired cart and malformed input.
      return /merchandise/i.test(first.message)
        ? "That item is no longer available."
        : "We couldn't update your bag. Please refresh and try again.";
    default:
      return GENERIC_ERROR;
  }
}

/** Never leak a raw Shopify/GraphQL message to the shopper. */
function toResult(cart: Cart | null, err: unknown, op: string, requestId: string): CartActionResult {
  if (err instanceof CartUserError) {
    log.warn("cart.user_error", { requestId, op, count: err.errors.length, code: err.errors[0]?.code ?? "" });
    return { cart, error: friendlyUserError(err), enabled: true };
  }
  log.error("cart.failed", { requestId, op, ...errorFields(err) });
  return { cart, error: GENERIC_ERROR, enabled: true };
}

const disabled = (): CartActionResult => ({ cart: null, error: UNAVAILABLE_ERROR, enabled: false });

function clampQuantity(quantity: number): number {
  if (!Number.isFinite(quantity)) return 1;
  return Math.min(MAX_QUANTITY, Math.max(1, Math.trunc(quantity)));
}

function isGid(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length < 300;
}

/**
 * Read the cart named by the cookie. Safe to call while rendering: it never
 * writes cookies and never throws, so a dead cart id just yields null.
 */
export async function getCurrentCart(): Promise<Cart | null> {
  if (!isShopifyConfigured()) return null;
  const requestId = randomUUID();
  const id = await readCartId();
  if (!id) return null;
  try {
    const cart = await getCart(id);
    if (!cart) log.info("cart.expired", { requestId, op: "getCurrentCart" });
    return cart;
  } catch (err) {
    log.error("cart.read_failed", { requestId, op: "getCurrentCart", ...errorFields(err) });
    return null;
  }
}

/** Add a variant, creating the cart lazily on the first add. */
export async function addToCart(variantId: string, quantity = 1): Promise<CartActionResult> {
  if (!isShopifyConfigured()) return disabled();
  const requestId = randomUUID();
  if (!isGid(variantId)) {
    log.warn("cart.bad_input", { requestId, op: "addToCart" });
    return { cart: null, error: "That item is no longer available.", enabled: true };
  }
  const lines = [{ merchandiseId: variantId, quantity: clampQuantity(quantity) }];
  const existingId = await readCartId();

  if (existingId) {
    try {
      const cart = await addCartLines(existingId, lines);
      log.info("cart.line_added", { requestId, op: "addToCart", lines: cart.lines.edges.length });
      return { cart, error: null, enabled: true };
    } catch (err) {
      if (!looksLikeMissingCart(err)) return toResult(null, err, "addToCart", requestId);
      // Cart expired or belongs to another store: drop it and start a new one.
      log.info("cart.recreating", { requestId, op: "addToCart" });
      await clearCartId();
    }
  }

  try {
    const cart = await createCart({ lines });
    await writeCartId(cart.id);
    log.info("cart.created", { requestId, op: "addToCart", lines: cart.lines.edges.length });
    return { cart, error: null, enabled: true };
  } catch (err) {
    return toResult(null, err, "addToCart", requestId);
  }
}

/** Set a line's quantity. Quantity 0 removes the line. */
export async function updateLine(lineId: string, quantity: number): Promise<CartActionResult> {
  if (!isShopifyConfigured()) return disabled();
  const requestId = randomUUID();
  if (!isGid(lineId)) return { cart: null, error: GENERIC_ERROR, enabled: true };
  if (quantity <= 0) return removeLine(lineId);

  const cartId = await readCartId();
  if (!cartId) return { cart: null, error: null, enabled: true };
  try {
    const cart = await updateCartLines(cartId, [{ id: lineId, quantity: clampQuantity(quantity) }]);
    log.info("cart.line_updated", { requestId, op: "updateLine", lines: cart.lines.edges.length });
    return { cart, error: null, enabled: true };
  } catch (err) {
    if (looksLikeMissingCart(err)) {
      await clearCartId();
      return { cart: null, error: null, enabled: true };
    }
    return toResult(null, err, "updateLine", requestId);
  }
}

export async function removeLine(lineId: string): Promise<CartActionResult> {
  if (!isShopifyConfigured()) return disabled();
  const requestId = randomUUID();
  if (!isGid(lineId)) return { cart: null, error: GENERIC_ERROR, enabled: true };

  const cartId = await readCartId();
  if (!cartId) return { cart: null, error: null, enabled: true };
  try {
    const cart = await removeCartLines(cartId, [lineId]);
    log.info("cart.line_removed", { requestId, op: "removeLine", lines: cart.lines.edges.length });
    return { cart, error: null, enabled: true };
  } catch (err) {
    if (looksLikeMissingCart(err)) {
      await clearCartId();
      return { cart: null, error: null, enabled: true };
    }
    return toResult(null, err, "removeLine", requestId);
  }
}

/** Apply a single discount code. An empty string clears any applied codes. */
export async function applyDiscountCode(code: string): Promise<CartActionResult> {
  if (!isShopifyConfigured()) return disabled();
  const requestId = randomUUID();
  const trimmed = typeof code === "string" ? code.trim().slice(0, 64) : "";

  const cartId = await readCartId();
  if (!cartId) return { cart: null, error: "Add something to your bag first.", enabled: true };
  try {
    const cart = await updateCartDiscountCodesFixed(cartId, trimmed ? [trimmed] : []);
    const applied = cart.discountCodes.some((d) => d.applicable);
    log.info("cart.discount_updated", { requestId, op: "applyDiscountCode", applied });
    if (trimmed && !applied) {
      return { cart, error: "That discount code isn't valid for this bag.", enabled: true };
    }
    return { cart, error: null, enabled: true };
  } catch (err) {
    if (looksLikeMissingCart(err)) {
      await clearCartId();
      return { cart: null, error: null, enabled: true };
    }
    return toResult(null, err, "applyDiscountCode", requestId);
  }
}
