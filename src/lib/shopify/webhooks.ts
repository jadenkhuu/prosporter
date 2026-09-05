/**
 * Pure helpers for the Shopify webhook receiver.
 *
 * Deliberately free of `server-only`, `next/*`, env reads and I/O: the route
 * handler at `src/app/api/webhooks/shopify/route.ts` owns all of that. Keeping
 * this module plain means `node --test` can import it directly (Node >= 22.18
 * strips the TypeScript types), so the security-critical logic is unit tested
 * without booting Next.
 *
 * The `./tags.ts` specifier carries its extension on purpose — it is what lets
 * plain Node resolve the import (`allowImportingTsExtensions` in tsconfig.json
 * permits it; bundlers resolve explicit extensions fine).
 */
import { Buffer } from "node:buffer";
import { createHmac, timingSafeEqual } from "node:crypto";

import { CACHE_TAGS } from "./tags.ts";

/** Length in bytes of a SHA-256 digest. */
const DIGEST_BYTES = 32;

/**
 * Constant-time verification of the `X-Shopify-Hmac-Sha256` header.
 *
 * Shopify signs the *raw* request body with the app's client secret and sends
 * the digest base64-encoded. The body must never be re-serialised before this
 * runs — `JSON.parse` + `JSON.stringify` changes bytes and breaks the digest.
 *
 * Returns false (never throws) for a missing header, a missing secret, a
 * malformed base64 value, or a mismatch.
 */
export function verifyShopifyHmac(
  rawBody: string | Uint8Array,
  headerValue: string | null | undefined,
  secret: string,
): boolean {
  if (!headerValue || !secret) return false;

  const provided = Buffer.from(headerValue.trim(), "base64");
  // `Buffer.from` silently drops invalid base64 rather than throwing, so the
  // length check doubles as the malformed-input guard.
  if (provided.length !== DIGEST_BYTES) return false;

  const body = typeof rawBody === "string" ? Buffer.from(rawBody, "utf8") : Buffer.from(rawBody);
  const expected = createHmac("sha256", secret).update(body).digest();
  return timingSafeEqual(expected, provided);
}

/** What a topic means for the cache. `known: false` marks a no-op topic. */
export type RevalidationPlan = {
  /** Normalised topic, e.g. `products/update`. */
  topic: string;
  /** Cache tags to revalidate, deduplicated and stable in order. */
  tags: string[];
  /** Handle found in the payload, when the topic carries one. */
  handle: string | null;
  /** False when the topic is not one we map; the route answers 200 and no-ops. */
  known: boolean;
};

const PRODUCT_TOPICS = new Set(["products/create", "products/update", "products/delete"]);
const COLLECTION_TOPICS = new Set([
  "collections/create",
  "collections/update",
  "collections/delete",
]);
const INVENTORY_TOPICS = new Set(["inventory_levels/update", "inventory_items/update"]);

/** Pull a non-empty `handle` string out of an unknown JSON payload. */
function readHandle(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const handle = (payload as Record<string, unknown>).handle;
  if (typeof handle !== "string") return null;
  const trimmed = handle.trim();
  return trimmed.length > 0 && trimmed.length <= 200 ? trimmed : null;
}

/**
 * Map an `X-Shopify-Topic` plus its payload onto the cache tags to revalidate.
 *
 * Delete topics usually arrive with only an id, so the fine-grained tag is
 * skipped and the coarse tag alone does the work.
 */
export function topicToTags(topic: string, payload: unknown): RevalidationPlan {
  const normalised = (topic ?? "").trim().toLowerCase();
  const handle = readHandle(payload);

  if (PRODUCT_TOPICS.has(normalised)) {
    const tags: string[] = [CACHE_TAGS.products];
    if (handle) tags.push(CACHE_TAGS.product(handle));
    return { topic: normalised, tags, handle, known: true };
  }

  if (COLLECTION_TOPICS.has(normalised)) {
    const tags: string[] = [CACHE_TAGS.collections];
    if (handle) tags.push(CACHE_TAGS.collection(handle));
    return { topic: normalised, tags, handle, known: true };
  }

  if (INVENTORY_TOPICS.has(normalised)) {
    // Availability is rendered on product pages and listings, so an inventory
    // change has to drop the product caches as well as the inventory tag.
    return {
      topic: normalised,
      tags: [CACHE_TAGS.inventory, CACHE_TAGS.products],
      handle: null,
      known: true,
    };
  }

  return { topic: normalised, tags: [], handle, known: false };
}

/** Every topic this receiver acts on. Kept in sync with scripts/webhooks/register_webhooks.py. */
export const HANDLED_TOPICS: readonly string[] = [
  ...PRODUCT_TOPICS,
  ...COLLECTION_TOPICS,
  ...INVENTORY_TOPICS,
];
