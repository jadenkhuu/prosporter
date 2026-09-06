/**
 * GA4 ecommerce item builders (CLNT-179).
 *
 * Pure, and deliberately free of runtime imports (`import type` only), so
 * `node --test` loads this module directly and so it is safe on both sides of
 * the server/client boundary. Nothing here reads env vars, touches `window` or
 * decides whether to send: that is `./track.ts`.
 *
 * Schema followed: https://developers.google.com/analytics/devguides/collection/ga4/reference/events
 * An ecommerce event carries `currency`, `value` and `items[]`; each item
 * carries `item_id`, `item_name`, `item_variant`, `price` and `quantity`.
 *
 * `item_id` is the merchant SKU when the variant has one, otherwise the numeric
 * Shopify variant id. That is the same identifier Shopify's own Google &
 * YouTube channel sends with the `purchase` event from checkout, so the
 * storefront-side and checkout-side events land on the same product in GA4.
 *
 * No personal data passes through here — no `user_id`, email, name, phone or
 * address — and none may be added.
 */
import type { CatalogVariant } from "@/lib/catalog-view";
import type { CartLine } from "@/lib/shopify/types";

export type AnalyticsItem = {
  item_id: string;
  item_name: string;
  item_variant?: string;
  item_brand?: string;
  item_category?: string;
  price: number;
  quantity: number;
  currency: string;
};

export type EcommerceParams = {
  currency: string;
  value: number;
  items: AnalyticsItem[];
  coupon?: string;
};

/** Shopify's placeholder variant title; never a real buyer-facing choice. */
const DEFAULT_VARIANT_TITLE = "Default Title";

/** GA4 rejects long-tail float noise in `value`; keep money at two decimals. */
export function round2(value: number): number {
  return Number.isFinite(value) ? Math.round(value * 100) / 100 : 0;
}

/** Storefront money amounts are decimal strings; treat junk as 0. */
function amount(money: { amount: string } | null | undefined): number {
  const value = Number(money?.amount);
  return Number.isFinite(value) ? value : 0;
}

/**
 * `gid://shopify/ProductVariant/4711` -> `4711`. Anything else comes back
 * unchanged, so a mock-catalog id or an already-numeric id still works.
 */
export function shortVariantId(gid: string | null | undefined): string {
  if (!gid) return "";
  const tail = gid.split("/").pop() ?? "";
  return tail || gid;
}

/** Drop Shopify's single-variant placeholder so `item_variant` stays meaningful. */
function variantLabel(title: string | null | undefined): string | undefined {
  const value = (title ?? "").trim();
  return value && value !== DEFAULT_VARIANT_TITLE ? value : undefined;
}

/** The minimum a product view model needs to describe itself to GA4. */
export type AnalyticsProduct = {
  handle: string;
  title: string;
  vendor: string | null;
  price: number;
  currency: string;
  categoryLabel?: string;
};

/**
 * One `items[]` entry for a product page. `variant` is null while the shopper
 * has not chosen one; the item then carries product-level price and handle.
 */
export function productItem(
  product: AnalyticsProduct,
  variant: CatalogVariant | null = null,
  quantity = 1,
): AnalyticsItem {
  const item: AnalyticsItem = {
    item_id: variant?.sku?.trim() || shortVariantId(variant?.id) || product.handle,
    item_name: product.title,
    price: round2(variant?.price ?? product.price),
    quantity: Math.max(1, Math.trunc(quantity) || 1),
    currency: variant?.currency ?? product.currency,
  };
  const label = variantLabel(variant?.title);
  if (label) item.item_variant = label;
  if (product.vendor) item.item_brand = product.vendor;
  if (product.categoryLabel) item.item_category = product.categoryLabel;
  return item;
}

/**
 * One `items[]` entry for a cart line. `quantity` overrides the line quantity,
 * which `add_to_cart` needs: adding a second unit of a line that already holds
 * three must report 1, not 4.
 */
export function cartLineItem(line: CartLine, quantity?: number): AnalyticsItem {
  const merchandise = line.merchandise;
  const options = merchandise.selectedOptions
    .filter((option) => option.value && option.value !== DEFAULT_VARIANT_TITLE)
    .map((option) => option.value)
    .join(" / ");
  const item: AnalyticsItem = {
    item_id: merchandise.sku?.trim() || shortVariantId(merchandise.id) || merchandise.product.handle,
    item_name: merchandise.product.title,
    price: round2(amount(merchandise.price)),
    quantity: Math.max(1, Math.trunc(quantity ?? line.quantity) || 1),
    currency: merchandise.price.currencyCode,
  };
  if (options) item.item_variant = options;
  return item;
}

/** The cart line holding a given variant, or null. Used to report what was added. */
export function findLineByVariant(lines: CartLine[], variantId: string): CartLine | null {
  return lines.find((line) => line.merchandise.id === variantId) ?? null;
}

/** `value` = sum of price x quantity across the items. */
export function itemsValue(items: AnalyticsItem[]): number {
  return round2(items.reduce((sum, item) => sum + item.price * item.quantity, 0));
}

function ecommerce(items: AnalyticsItem[], fallbackCurrency: string, coupon?: string): EcommerceParams {
  const params: EcommerceParams = {
    currency: items[0]?.currency ?? fallbackCurrency,
    value: itemsValue(items),
    items,
  };
  const code = coupon?.trim();
  if (code) params.coupon = code;
  return params;
}

/** `view_item` payload for the product page. */
export function viewItemParams(
  product: AnalyticsProduct,
  variant: CatalogVariant | null = null,
): EcommerceParams {
  return ecommerce([productItem(product, variant)], product.currency);
}

/** `add_to_cart` payload for one line, reporting only the quantity just added. */
export function addToCartParams(
  line: CartLine,
  addedQuantity: number,
  fallbackCurrency = "AUD",
): EcommerceParams {
  return ecommerce([cartLineItem(line, addedQuantity)], fallbackCurrency);
}

/**
 * `begin_checkout` payload for the whole bag.
 *
 * `value` defaults to the sum of the lines, but the drawer passes Shopify's
 * costed total so a cart-level discount is reflected; `coupon` carries the
 * applied discount code when there is one.
 */
export function beginCheckoutParams(
  lines: CartLine[],
  options: { coupon?: string; value?: number; currency?: string } = {},
): EcommerceParams {
  const params = ecommerce(
    lines.map((line) => cartLineItem(line)),
    options.currency ?? "AUD",
    options.coupon,
  );
  if (typeof options.value === "number" && Number.isFinite(options.value)) {
    params.value = round2(options.value);
  }
  if (options.currency) params.currency = options.currency;
  return params;
}
