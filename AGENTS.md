<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Project scope

This repository is strictly for the ProSporter ecommerce storefront, its WooCommerce-to-Shopify migration, and its headless Next.js frontend.

Do not add, plan, or document unrelated marketing sites, club sites, CMS projects, social feeds, sports-data feeds, or other deliverables from the wider client agreement. References to the client or wider agreement are permitted only when they directly govern ProSporter requirements.

# Conventions verified against Next.js 16.3 (read `node_modules/next/dist/docs/` before changing)

- `cacheComponents` is **off**. Data caching uses the classic path: `fetch(url, { cache: "force-cache", next: { tags, revalidate } })`. Do not add `"use cache"` / `cacheTag()` / `cacheLife()` without turning the flag on and migrating every route.
- `revalidateTag(tag, "max")` — the two-argument form. The single-argument form is deprecated.
- `error.tsx` / `global-error.tsx` receive `{ error, retry }`. Use `retry()` (re-fetches); `reset()` exists but is rarely right.
- `react-hooks/set-state-in-effect` is an error. Don't call `setState` synchronously inside `useEffect`; use a ref, lazy initial state, or `useSyncExternalStore`.
- `import "server-only"` needs no package install; Next resolves it. Every module that reads `process.env.SHOPIFY_*` or holds a token must start with it.

# Shopify data layer (`src/lib/shopify/`)

- `config.ts` is the only reader of Shopify env vars. `index.ts` is the only import for pages/actions. Never call `shopifyFetch` from a component.
- Catalog reads: `force-cache` + tags from `tags.ts` + `CATALOG_REVALIDATE_SECONDS`. Carts and mutations: `no-store`.
- Storefront API version defaults to `2026-07`; override with `SHOPIFY_STOREFRONT_API_VERSION`.
- Logging goes through `src/lib/log.ts` (JSON lines). Never log personal data or tokens; log request IDs, handles and counts.
- `SHOPIFY_OPTIONAL=1` lets a production server boot without Shopify. Remove it from CI and hosting once the store exists.
- `exports/` (WooCommerce raw data) and `.env.local` are git-ignored and must stay so. `docs/audit/` is derived, PII-free, and committable.

# Shopify Admin API (`scripts/migration/shopify_admin.py`, Python only)

- The storefront never uses the Admin API. Admin access lives in the migration scripts and is minted per run from `SHOPIFY_ADMIN_CLIENT_ID` / `SHOPIFY_ADMIN_CLIENT_SECRET` (client credentials grant, 24h tokens, cached under `exports/migration/`). Never paste a `shpat_` token into code, docs, Linear or git.
- `python3 scripts/migration/shopify_admin.py doctor` must pass (all required scopes granted) before any load against the real store. Store facts it reports: internal domain `ihuvab-u2.myshopify.com` (primary `prosporter.myshopify.com`), location "Shop location", Headless publication "ProSporter Dev".
- Admin API version is pinned with the Storefront version (`2026-07`, `SHOPIFY_API_VERSION` in `scripts/migration/common.py`). Several 2026-07 input shapes differ from older docs (collections, inventory, customer addresses, discounts); `docs/migration/README.md` has the verified table. Introspect the live schema before adding a mutation.
- `run.py --target shopify` requires `--live` and its own `--store` ledger. Never point a live load at `exports/migration/fake-store`. Products load as DRAFT; only `shopify_admin.py publish` changes status, and only for QA.

# Local checks (Actions minutes are limited)

- `npm run check` = the CI job (lint, typecheck, build, audit). `npm run hooks:install` wires it into `git pre-push`; `git push --no-verify` skips it deliberately.
- The workflow triggers on pull requests and manual dispatch only until the org has Actions minutes again.
