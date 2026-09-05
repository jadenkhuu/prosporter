# Deployment (Vercel)

The storefront is a Next.js 16 app deployed on Vercel. Shopify is the backend; the
app only ever holds the **public** Storefront token and the webhook signing secret.
No Admin API credential is ever configured on the host.

## One-time setup

1. Vercel dashboard → **Add New → Project → Import** `stealth-startup-2026/prosporter`.
   Framework preset: Next.js (auto-detected). Root directory: repository root.
   Build command, output and install command: defaults. Node.js: 22.x (pinned in
   `package.json` `engines`).
2. **Environment variables** (Settings → Environment Variables). Set for Production and
   Preview; values come from the local `.env.local`, never from git:

   | Name | Value | Notes |
   |---|---|---|
   | `SHOPIFY_STORE_DOMAIN` | `prosporter.myshopify.com` | `*.myshopify.com` only |
   | `SHOPIFY_STOREFRONT_TOKEN` | Headless channel public token | dev storefront token for now; swap for a production storefront token before go-live |
   | `SHOPIFY_WEBHOOK_SECRET` | ProSporter-migration app client secret | HMAC key for `/api/webhooks/shopify` (see `docs/webhooks.md`) |
   | `LOG_LEVEL` | `info` | optional |

   Do **not** set `SHOPIFY_OPTIONAL` on Vercel. It exists only so CI can build without a
   store; on the host it would let a misconfigured deploy boot in mock mode.
3. Deploy. Production tracks `main`; every other branch and PR gets a preview URL.
4. Region is pinned to Sydney (`syd1`) in `vercel.json` so server rendering sits next to
   the Australian shoppers and Shopify's AU checkout.

## After the first deploy

- Register webhooks against the deployment URL (dry run first):

  ```bash
  python3 scripts/webhooks/register_webhooks.py ensure https://<deployment-host>
  python3 scripts/webhooks/register_webhooks.py ensure https://<deployment-host> --apply
  ```

  Use the stable production hostname (custom domain or the `*.vercel.app` production
  alias), not a per-commit preview URL.
- Verify: `curl -sI https://<host>/product/nago` → 200; `https://<host>/cart` → 410;
  `https://<host>/product/<any>/` → single 308. `python3 scripts/redirects/verify_redirects.py`
  can be pointed at the host.

## Caching model on Vercel

Catalog, content and search reads use the Next data cache with tags (`src/lib/shopify/tags.ts`)
and time-based revalidation (1 h catalog, 5 min search). On Vercel that cache is shared
across regions and instances, so a webhook hitting one function invalidates for all.
The webhook route's duplicate-suppression LRU is per instance and best effort; Shopify
retries are idempotent anyway because revalidation is.

## Custom domain and go-live (later)

`prosporter.com.au` moves to Vercel at cutover (see `docs/migration/cutover-runbook.md`).
Checkout stays on Shopify's domain until a Shopify checkout domain is configured;
customer-account URLs likewise. Both are client decisions on CLNT-303.

## Rollback

Vercel → Deployments → Promote a previous production deployment. Shopify data is
unaffected by frontend rollbacks.
