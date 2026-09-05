import "server-only";

import { revalidateTag } from "next/cache";

import { errorFields, log } from "@/lib/log";
import { topicToTags, verifyShopifyHmac } from "@/lib/shopify/webhooks";

/**
 * Shopify webhook receiver.
 *
 * Shopify POSTs a JSON body signed with the app's client secret. We verify the
 * signature over the raw bytes, check the shop domain, then revalidate the
 * cache tags in `src/lib/shopify/tags.ts` for the affected resource. The
 * storefront holds no Admin token: this route only ever invalidates caches.
 *
 * Shopify retries any response that is not 2xx and gives up after ~48 hours,
 * so the handler stays cheap and answers well inside the 5 second budget.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Known aliases for this store. The internal domain is what Shopify actually sends. */
const KNOWN_SHOPS = ["ihuvab-u2.myshopify.com", "prosporter.myshopify.com"];

/**
 * Best-effort duplicate suppression.
 *
 * Shopify redelivers on timeouts, so the same `X-Shopify-Webhook-Id` can arrive
 * twice. This is a per-process LRU: it is NOT shared across instances or across
 * a cold start, so multi-instance dedupe is explicitly out of scope. A missed
 * dedupe only costs a redundant revalidation, which is harmless.
 */
const SEEN_LIMIT = 512;
const SEEN_TTL_MS = 10 * 60 * 1000;
const seen = new Map<string, number>();

function seenBefore(webhookId: string): boolean {
  if (!webhookId) return false;
  const now = Date.now();
  const previous = seen.get(webhookId);
  if (previous !== undefined && now - previous < SEEN_TTL_MS) {
    seen.delete(webhookId);
    seen.set(webhookId, now);
    return true;
  }
  seen.delete(webhookId);
  seen.set(webhookId, now);
  while (seen.size > SEEN_LIMIT) {
    const oldest = seen.keys().next().value;
    if (oldest === undefined) break;
    seen.delete(oldest);
  }
  return false;
}

/** Shop domains this receiver accepts, lower-cased. */
function allowedShops(): Set<string> {
  const configured = (process.env.SHOPIFY_WEBHOOK_ALLOWED_SHOPS ?? "")
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  if (configured.length > 0) return new Set(configured);

  const shops = new Set(KNOWN_SHOPS);
  const fromEnv = (process.env.SHOPIFY_STORE_DOMAIN ?? "")
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  if (fromEnv) shops.add(fromEnv);
  return shops;
}

function json(status: number, body: Record<string, unknown>): Response {
  return Response.json(body, { status, headers: { "cache-control": "no-store" } });
}

export async function POST(request: Request): Promise<Response> {
  const topicHeader = request.headers.get("x-shopify-topic") ?? "";
  const webhookId = request.headers.get("x-shopify-webhook-id") ?? "";
  const shop = (request.headers.get("x-shopify-shop-domain") ?? "").trim().toLowerCase();

  const secret = (process.env.SHOPIFY_WEBHOOK_SECRET ?? "").trim();
  if (!secret) {
    // Never answer 200 here: a 500 makes Shopify retry, so events survive a
    // misconfigured deploy instead of being silently dropped.
    log.error("shopify.webhook.misconfigured", {
      reason: "SHOPIFY_WEBHOOK_SECRET is not set",
      topic: topicHeader,
      webhookId,
    });
    return json(500, { ok: false, error: "webhook receiver not configured" });
  }

  let rawBody: string;
  try {
    rawBody = await request.text();
  } catch (error) {
    log.warn("shopify.webhook.body_unreadable", { topic: topicHeader, webhookId, ...errorFields(error) });
    return json(400, { ok: false, error: "unreadable body" });
  }

  // Signature first: everything below this line trusts the headers.
  if (!verifyShopifyHmac(rawBody, request.headers.get("x-shopify-hmac-sha256"), secret)) {
    log.warn("shopify.webhook.rejected", {
      reason: "invalid_hmac",
      topic: topicHeader,
      webhookId,
      shop,
    });
    return json(401, { ok: false, error: "invalid signature" });
  }

  if (!allowedShops().has(shop)) {
    log.warn("shopify.webhook.rejected", { reason: "unexpected_shop", topic: topicHeader, webhookId, shop });
    return json(403, { ok: false, error: "unexpected shop" });
  }

  if (seenBefore(webhookId)) {
    log.info("shopify.webhook.duplicate", { topic: topicHeader, webhookId, shop });
    return json(200, { ok: true, duplicate: true });
  }

  let payload: unknown = null;
  try {
    payload = rawBody ? JSON.parse(rawBody) : null;
  } catch {
    // A signed body that is not JSON is odd but not actionable; the coarse tag
    // still gets revalidated from the topic alone.
    log.warn("shopify.webhook.unparsable_payload", { topic: topicHeader, webhookId, shop });
  }

  const plan = topicToTags(topicHeader, payload);
  if (!plan.known) {
    log.info("shopify.webhook.ignored", { topic: plan.topic, webhookId, shop });
    return json(200, { ok: true, ignored: true });
  }

  try {
    for (const tag of plan.tags) {
      revalidateTag(tag, "max");
    }
  } catch (error) {
    log.error("shopify.webhook.revalidate_failed", {
      topic: plan.topic,
      webhookId,
      shop,
      ...errorFields(error),
    });
    return json(500, { ok: false, error: "revalidation failed" });
  }

  log.info("shopify.webhook.revalidated", {
    topic: plan.topic,
    webhookId,
    shop,
    handle: plan.handle,
    tags: plan.tags.length,
  });
  return json(200, { ok: true, topic: plan.topic, tags: plan.tags });
}
