# Shopify webhooks

Catalog reads in `src/lib/shopify/` are cached with `force-cache` plus the tags in
`src/lib/shopify/tags.ts`. Nothing in the storefront polls Shopify, so a price,
title, image or stock change would sit behind a stale cache for up to
`CATALOG_REVALIDATE_SECONDS` (1 hour). Webhooks close that gap: Shopify posts an
event, the receiver revalidates the affected tags, and the next visitor triggers
the refetch.

## Pieces

| Thing | Where |
| --- | --- |
| Receiver (POST) | `src/app/api/webhooks/shopify/route.ts` → `/api/webhooks/shopify` |
| Pure helpers (HMAC, topic → tags) | `src/lib/shopify/webhooks.ts` |
| Unit tests | `src/lib/shopify/__tests__/webhooks.test.mjs` (`npm test`) |
| Registration script | `scripts/webhooks/register_webhooks.py` |
| Cache tags | `src/lib/shopify/tags.ts` |

## HMAC verification with a Dev Dashboard app

The migration app ("ProSporter-migration") is a Shopify Dev Dashboard app
installed on the client's store. Webhook subscriptions it creates are signed
with **the app's client secret** — the same value the migration scripts read as
`SHOPIFY_ADMIN_CLIENT_SECRET`. There is no separate "webhook secret" to generate
and no shared secret in the Shopify admin UI to copy; the Notifications page in
the store admin has its own secret, but that one only applies to webhooks
created there, not to app-owned subscriptions.

So on the storefront host:

```
SHOPIFY_WEBHOOK_SECRET = <the ProSporter-migration app's client secret>
```

Shopify computes `base64(HMAC-SHA256(raw_request_body, client_secret))` and
sends it as `X-Shopify-Hmac-Sha256`. The receiver recomputes it over the raw
body bytes and compares with `crypto.timingSafeEqual`.

The signature is over the **exact bytes** Shopify sent. `await request.text()`
runs before any parsing, and the body is never re-serialised before verifying —
`JSON.parse` followed by `JSON.stringify` changes whitespace and unicode escapes
and would break every signature.

The storefront holds no Admin API token and must never be given one. The
receiver can only invalidate caches; it cannot read or write store data.

### Environment variables

| Variable | Required | Meaning |
| --- | --- | --- |
| `SHOPIFY_WEBHOOK_SECRET` | yes | The app's client secret. Without it the route answers **500** (so Shopify retries) rather than silently accepting or dropping events. |
| `SHOPIFY_WEBHOOK_ALLOWED_SHOPS` | no | Comma-separated `*.myshopify.com` domains to accept. When unset, the receiver accepts `ihuvab-u2.myshopify.com`, `prosporter.myshopify.com` and whatever `SHOPIFY_STORE_DOMAIN` is set to. |
| `SHOPIFY_STORE_DOMAIN` | already required | Also feeds the default allow-list. |

The store has two names: the internal domain `ihuvab-u2.myshopify.com` and the
primary `prosporter.myshopify.com`. Shopify sends the internal one in
`X-Shopify-Shop-Domain`, which is why both are accepted by default.

## Topics and revalidation mapping

`topicToTags(topic, payload)` in `src/lib/shopify/webhooks.ts`:

| `X-Shopify-Topic` | Tags revalidated |
| --- | --- |
| `products/create`, `products/update`, `products/delete` | `shopify:products` + `shopify:product:<handle>` when the payload carries a handle |
| `collections/create`, `collections/update`, `collections/delete` | `shopify:collections` + `shopify:collection:<handle>` when present |
| `inventory_levels/update`, `inventory_items/update` | `shopify:inventory` + `shopify:products` (availability renders on product and listing pages) |
| anything else | none; the route logs and answers 200 |

Delete events usually arrive with only an id, so the fine-grained tag is skipped
and the coarse tag does the work.

Revalidation uses `revalidateTag(tag, "max")` — the two-argument form required
by Next 16.3. Pages using the tag refresh as they are next visited, serving
stale content while the refetch runs, rather than all at once.

## Registering the subscriptions

```bash
python3 scripts/webhooks/register_webhooks.py list                                  # what exists today
python3 scripts/webhooks/register_webhooks.py ensure https://www.prosporter.co.uk   # dry run (default)
python3 scripts/webhooks/register_webhooks.py ensure https://www.prosporter.co.uk --apply
```

`ensure` is idempotent: it creates a subscription per topic when missing,
updates the `uri`/`format` when they drift, leaves correct ones alone, and never
touches a topic outside its managed list. Extra subscriptions on a managed topic
are reported and only removed with `--prune`. `--with-inventory-items` adds
`INVENTORY_ITEMS_UPDATE`, which is off by default because it also fires on
cost/SKU edits; `INVENTORY_LEVELS_UPDATE` already covers stock movement.

Registered topics: `PRODUCTS_CREATE`, `PRODUCTS_UPDATE`, `PRODUCTS_DELETE`,
`COLLECTIONS_CREATE`, `COLLECTIONS_UPDATE`, `COLLECTIONS_DELETE`,
`INVENTORY_LEVELS_UPDATE`. Endpoint: `<BASE_URL>/api/webhooks/shopify`, format
JSON.

### 2026-07 Admin API shapes (introspected against the live store)

`WebhookSubscriptionInput` has fields `format`, `includeFields`, `filter`,
`metafieldNamespaces`, `metafields`, `name`, `uri`. The destination is **`uri`
(a `String`)** — the older `callbackUrl` field and the
`WebhookSubscriptionEndpoint` union are gone.

```graphql
mutation CreateWebhook($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri format apiVersion { handle } }
    userErrors { field message }
  }
}
# variables: { "topic": "PRODUCTS_UPDATE", "sub": { "uri": "https://…/api/webhooks/shopify", "format": "JSON" } }

mutation UpdateWebhook($id: ID!, $sub: WebhookSubscriptionInput!) { webhookSubscriptionUpdate(id: $id, webhookSubscription: $sub) { … } }
mutation DeleteWebhook($id: ID!) { webhookSubscriptionDelete(id: $id) { deletedWebhookSubscriptionId userErrors { field message } } }
```

`WebhookSubscription.apiVersion` is an `ApiVersion` object, not a scalar; select
`apiVersion { handle }`. `webhookSubscriptions(...)` returns only subscriptions
owned by the calling app — subscriptions created by other apps or by the store's
Notifications page are invisible here and cannot be modified or deleted by this
script.

## Testing locally with a signed curl

Start the app with a throwaway secret:

```bash
SHOPIFY_WEBHOOK_SECRET=test PORT=3113 npm run start
```

Sign a body and post it (the python one-liner prints the base64 digest):

```bash
BODY='{"id":123,"handle":"nago"}'
SIG=$(python3 -c 'import base64,hashlib,hmac,sys;print(base64.b64encode(hmac.new(sys.argv[1].encode(),sys.argv[2].encode(),hashlib.sha256).digest()).decode())' "test" "$BODY")

curl -i -X POST http://localhost:3113/api/webhooks/shopify \
  -H 'Content-Type: application/json' \
  -H 'X-Shopify-Topic: products/update' \
  -H 'X-Shopify-Shop-Domain: prosporter.myshopify.com' \
  -H 'X-Shopify-Webhook-Id: local-test-1' \
  -H "X-Shopify-Hmac-Sha256: $SIG" \
  --data "$BODY"
```

Expected: `200 {"ok":true,"topic":"products/update","tags":["shopify:products","shopify:product:nago"]}`.
Repeat the same command unchanged and the second call answers
`{"ok":true,"duplicate":true}`. Drop the signature header and it is `401`.

`--data` must be byte-identical to the string that was signed; `--data-binary
@file` is safer for payloads containing newlines.

Note that a local `npm run start` also needs the usual Shopify env (or
`SHOPIFY_OPTIONAL=1`) to boot, and `revalidateTag` only affects that process's
own cache.

## Failure modes

| Symptom | Response | Cause / fix |
| --- | --- | --- |
| `SHOPIFY_WEBHOOK_SECRET` unset on the host | 500 | Deliberate: Shopify retries for ~48 hours, so events survive a misconfigured deploy. Set the app client secret. |
| Signature mismatch | 401 | Wrong secret (a rotated client secret, or the Notifications-page secret instead of the app's), or a proxy/CDN that rewrote or recompressed the body. |
| Missing `X-Shopify-Hmac-Sha256` | 401 | Not from Shopify. |
| Unrecognised `X-Shopify-Shop-Domain` | 403 | Signature was valid but the shop is not in the allow-list. Add it to `SHOPIFY_WEBHOOK_ALLOWED_SHOPS`. |
| Unknown topic | 200, no-op | A subscription exists for a topic the receiver does not map. Harmless; remove the subscription or extend `topicToTags`. |
| Duplicate delivery | 200, `duplicate: true` | Shopify redelivered. Dedupe is a per-process 512-entry / 10-minute LRU keyed on `X-Shopify-Webhook-Id`; it is **best effort only**. Multi-instance and cross-restart dedupe are out of scope — a missed dedupe costs one redundant revalidation, which is harmless because revalidation is idempotent. |
| Handler slower than 5s | Shopify retries | The handler does no network I/O, so this should not happen. Never add a Shopify fetch to it. |
| Product changed but the page is stale | – | Check the subscription exists (`list`), that the URI matches the deployed host, and that the page's fetch actually carries the tag. On a multi-instance host, `revalidateTag` must reach a shared cache handler; with per-instance in-memory caches only the instance that received the webhook is invalidated. |
| App uninstalled / reinstalled | – | Subscriptions are app-owned and disappear with the app. Re-run `ensure --apply`, and re-check `SHOPIFY_WEBHOOK_SECRET` if the client secret changed. |

## Out of scope

- Cross-instance idempotency (needs shared storage such as Redis or KV).
- Order, customer and cart topics: the storefront caches none of that.
- Retry/dead-letter bookkeeping beyond Shopify's own retry schedule.
