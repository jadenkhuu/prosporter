# ProSporter migration pipeline (CLNT-305)

Repeatable, deterministic WooCommerce → Shopify migration pipeline plus its dry-run
evidence. There is **no Shopify store yet**, so the load stage runs entirely against a
file-backed fake Admin API. Nothing in this pipeline makes a network call.

Everything in `docs/migration/` is derived and PII-free. Every artefact that contains
real customer or catalog data is written under `exports/` (git-ignored) and never leaves it.

## Stages

| Stage | What it does | Output |
|---|---|---|
| `extract` | Reads `exports/*.json`, checks every required entity is present, records the snapshot time from `exports/_manifest.json`. No network. | `source-summary.json` |
| `transform` | Applies execution-plan section 7 normalization and the approved IA, emits Shopify-shaped JSONL. | one `.jsonl` per record type |
| `load` | Upserts every record into the target in the plan's load order. | `load-result.json`, the fake store, `mapping.json` |
| `reconcile` | Field-level source-vs-target comparison for every item in the plan's dry-run reconciliation list. | `reconciliation.json`, `docs/migration/reconciliation-latest.md`, `docs/migration/exception-register.csv` |
| `all` | extract → transform → load → reconcile in one process. | all of the above plus `run-manifest.json` |
| `prove` | Runs `all` twice on identical inputs, then once on a controlled delta, and diffs the fake store each time. | `docs/migration/idempotency-proof.md`, `exports/migration/proof.json` |

## CLI

```bash
# full dry run against the real export snapshot
python3 scripts/migration/run.py all

# same, into a named run directory
python3 scripts/migration/run.py all --run-id 2026-09-05a

# CI / no exports needed: 5 synthetic products, 2 pages, 1 post, 1 coupon, 2 fake customers
python3 scripts/migration/run.py all --source scripts/migration/fixtures \
    --store exports/migration/fixture-store

# stages can be run one at a time; each reads the previous stage's output
python3 scripts/migration/run.py extract   --run-id 2026-09-05a
python3 scripts/migration/run.py transform --run-id 2026-09-05a
python3 scripts/migration/run.py load      --run-id 2026-09-05a
python3 scripts/migration/run.py reconcile --run-id 2026-09-05a

# idempotency + delta proof (writes docs/migration/idempotency-proof.md)
python3 scripts/migration/run.py prove

# tests
python3 -m unittest discover -s scripts/migration/tests
```

Flags: `--source` (export directory, default `exports/`), `--target` (`fake` default,
`shopify-admin` raises `NotImplementedError`), `--store` (fake-store directory),
`--reset-store` (load from scratch), `--no-docs` (skip the committed reports),
`--fail-on-critical` (exit 2 when unresolved critical exceptions remain — the quality gate).

Python 3.11+, standard library only. Deterministic: the same inputs produce byte-identical
JSONL, so two runs can be diffed.

## Run layout

```text
exports/migration/
  <run-id>/
    run-manifest.json        run id, pipeline commit, source snapshot, API version, target, counts
    source-summary.json      source-side counts
    products.jsonl  variants.jsonl  media.jsonl  collections.jsonl  metafields.jsonl
    metafield_definitions.jsonl  pages.jsonl  articles.jsonl  customers.jsonl
    discounts.jsonl  id_map.jsonl
    load-result.json         per-record create/update/unchanged outcome and destination id
    exceptions.jsonl         the full structured error set for the run
    reconciliation.json      every reconciliation check
  fake-store/
    store.json               every fake Shopify object, keyed by identity, with a checksum
    mapping.json             source key -> gid://shopify/... plus SKU and woo-id indexes
  proof-store/, proof-run-1..3/, delta-source/, proof.json     (written by `prove`)
```

`run-manifest.json` pins: run id, pipeline version, `git rev-parse HEAD`, source snapshot
timestamp, Shopify API version `2026-07`, target name, record counts, load stats,
exception counts and the reconciliation summary.

## Record shapes

Every record carries `source: {woo_id, woo_type, source_snapshot}`. Products are always
`status: DRAFT` — dry runs never publish. Products also get a private `migration.woo_id`
metafield so the trace survives into Shopify itself (plan section 6).

Storefront metafields follow `src/lib/shopify/fragments.ts` `PRODUCT_METAFIELD_IDENTIFIERS`:
`prosporter.surface`, `prosporter.club`, `prosporter.gender` are populated from the IA
mapping. `prosporter.size_guide` and `prosporter.personalisation` are **defined but not
populated**: no size-guide field exists in the source, and the PPOM personalisation evidence
lives on order lines (workstream 5), not on products. Populating `personalisation` is a
follow-up once the team-kit line-item property model is approved.

## Mapping manifest

`exports/migration/fake-store/mapping.json` is the anti-duplication key. Identity per
resource:

| Resource | Identity key | Why |
|---|---|---|
| Product, Collection, Page, Article | `handle` | stable and human-checkable |
| ProductVariant, InventoryItem | `woo:<variation id>` | **SKUs are not unique in the source** (6 SKUs are shared by up to 19 variations), so SKU cannot be the identity |
| MediaImage | `<product handle>:<original url>` | one product can reuse an image |
| Metafield | `<owner>:<handle>:<namespace>.<key>` | |
| Customer | `email` | |
| DiscountCodeNode | `code` | |

`indexes` in the same file gives secondary lookups (`variant_sku`, `variant_woo_id`,
`product_woo_id`, `page_woo_id`, `article_woo_id`, `customer_woo_id`). Customer emails are
never used as an index key and never leave `exports/`.

## Error model

Each exception is a JSON object:

```json
{"record": {"type": "variant", "id": 1965, "ref": "PROS-PROT00WAM-1965"},
 "stage": "transform", "severity": "high", "code": "variant_missing_option_value",
 "message": "...", "owner": "client", "retry_status": "needs-decision", "detail": {}}
```

* `severity`: `critical` (blocks the load; fails `--fail-on-critical`), `high`, `medium`, `low`.
* `owner`: `client` (needs a merchandising or data decision) or `purpl` (we fix it).
* `retry_status`: `auto-retryable`, `needs-decision`, `wont-fix`, `resolved`.

A record with a blocking exception is marked `held: true` and skipped by the load, so every
count difference in `reconciliation-latest.md` is explained by a named exception rather than
silently absorbed. `docs/migration/exception-register.csv` is the committed, PII-free view:
product/variant/page ids and slugs only; customers appear as `customer:<woo id>`.

## Loader interface

```python
class Target:
    def upsert(self, resource: str, key: str, payload: dict) -> tuple[str, str]:
        """Return (destination_id, "created" | "updated" | "unchanged")."""
    def finish(self) -> None: ...
    def counts(self) -> dict: ...
```

`upsert` must be idempotent: the same key with the same payload must not create a second
object and must report `unchanged`. `loader.LOAD_ORDER` encodes the plan's load order
(definitions and empty collections → products/options → variants → media → inventory →
collection membership, tags and metafields → pages → articles → customers → discounts).
Redirects (step 9) belong to the redirects workstream; final publication to the Headless
channel (step 10) happens after QA and is out of scope for a dry run.

### What is stubbed and why

`FakeShopifyTarget` is the only working target. It assigns `gid://shopify/<Resource>/<n>`
ids from a persisted counter, stores each object with a payload checksum, and on rerun
compares checksums so an unchanged record reports `unchanged` and keeps its id.

`ShopifyAdminTarget` raises `NotImplementedError` on construction. It exists so the real
implementation has a named home and a documented contract. When the store is provisioned,
implement it against Admin API `2026-07`:

| Stage | Mutation |
|---|---|
| metafield definitions | `metafieldDefinitionCreate` |
| collections | `collectionCreate` / `collectionUpdate` |
| products and options | `productSet` |
| variants | `productVariantsBulkCreate` / `productVariantsBulkUpdate` |
| media | `fileCreate`, then `productCreateMedia` / `productVariantAppendMedia` |
| inventory | `inventorySetQuantities`, `inventoryItemUpdate` |
| collection membership | `collectionAddProducts` / `collectionRemoveProducts` |
| metafields | `metafieldsSet` |
| pages | `pageCreate` / `pageUpdate` |
| articles | `articleCreate` / `articleUpdate` |
| customers | `customerCreate` / `customerUpdate` |
| discounts | `discountCodeBasicCreate` / `discountCodeBasicUpdate` |
| redirects | `urlRedirectCreate` (redirects workstream) |

For products, variants and media use `bulkOperationRunMutation` with a staged JSONL upload.
Keep the per-record upsert semantics: resolve existing destination ids from `mapping.json`
before the bulk run so a rerun updates instead of creating duplicates.

## Normalization decisions applied automatically

1. `Color` and `Colour` merge into one `Colour` option.
2. `Navy Blue` → `Navy`; `Gray` / `Light Gray` → `Grey`. Two-tone values normalise per half
   (`Black / Gray` → `Black / Grey`).
3. `Male` / `Man` → `Men`; `Female` → `Women`.
4. `XXL` → `2XL`, `3X` → `3XL`, `SM` → `S/M`, `ML` → `M/L`, `XXS` → `2XS`.
5. Numeric sock sizing (`36-41`, `42`) becomes a separate `Sock Size` option and never mixes
   with apparel sizing. A single attribute containing both raises `mixed_size_systems`.
6. **A synonym merge is reverted if it would collide two of the same product's variants.**
   The raw values are kept and `option_value_collision` is raised (e.g. one product sells
   both `3X` and `3XL`).
7. An option whose variations only ever use one value is dropped, making the product
   single-variant (`Title / Default Title`). This is how the `Hats` attribute is retired.
8. Blank SKUs are filled with `PS-<wooProductId>-<wooVariationId>` and flagged
   `sku_generated: true`. Duplicate SKUs are **never** rewritten; they raise `duplicate_sku`.
9. Every original category and tag survives as a `legacy:<slug>` tag, alongside
   `type:`, `surface:`, `club:` and `gender:` tags.
10. Product type comes from the approved IA (tops, shorts-pants, hoodies-jackets, jerseys,
    accessories — protective gear and coaching folded into accessories). A type inferred from
    the product name or falling back to accessories is flagged for a client decision.

## Decisions routed to the exception register (not made by the pipeline)

| Attribute / case | Why it was escalated |
|---|---|
| `Condition` (`Used`, `Returned`, `Defect`, `With Surname`, `Without Surname`, `No Number`) | mixes goods condition with jersey personalisation; not clearly a merchandising axis |
| `Number` (jersey numbers 1–43) | a per-order line-item property, not a variant axis |
| Products with 4 variant attributes | exceeds Shopify's 3-option limit; the client must choose which axes survive |
| Duplicate SKUs | Shopify needs unique SKUs for inventory; the client supplies them |
| Variations with no price anywhere | cannot be loaded without a price |
| WooCommerce "Any &lt;option&gt;" variations | no Shopify equivalent; must be expanded at source or by an approved rule |
| The Easy Product Bundles product | no Shopify equivalent; rebuild manually |

## Cutover-relevant open decisions (from the audit)

1. **SKUs** — 219 variations have no SKU and 6 SKU values are shared by up to 19 variations
   (`PROT00SEM-1`). The pipeline generates deterministic placeholders and reports duplicates.
   The client must either confirm the generated pattern or supply real SKUs before cutover.
2. **Missing prices** — 56 variations have no regular price. Most inherit the parent product
   price; the remainder have no price anywhere and are held out of the load.
3. **Missing images** — 44 published products have no image. They still migrate; the
   storefront will show a placeholder until the client supplies photography.
4. **Attribute normalization for `Condition`, `Number` and `Hats`** — `Hats` is retired as a
   label automatically. `Condition` and `Number` block their products until the client
   decides between variant options, line-item properties (personalisation) or removal.
5. **Bundle product** — the single Easy Product Bundles product must be rebuilt manually.
6. **Tax** — the source has prices-include-tax and tax calculation on, but **zero tax rates
   configured**. Variants carry `taxable` from the source `tax_status`; Shopify tax settings
   and GST treatment must be confirmed before the store goes live.
7. **Weights** — 721 of 917 variations have no weight, so weight-based shipping rates cannot
   be calculated. The store currently uses flat/free rates, which the pipeline does not migrate.
8. **Marketing consent** — the audit found no consent field anywhere in the source, so every
   migrated customer is `NOT_SUBSCRIBED`. Consent is never invented.
9. **Duplicate WordPress pages** (`cart-2`, `blog-2`, `1687-2`, …) — flagged; the client
   confirms the canonical set. WooCommerce functional pages (cart, checkout, my-account,
   wishlist) are held because the Next.js storefront owns those routes.
10. **Advanced Coupons rules** — 4 of the 5 coupons carry Advanced Coupons / Flexible Coupons
    metadata that `discountCodeBasic` cannot express. They migrate as basic discounts with the
    unsupported rules listed.

## Data-handling rules

* `exports/` is git-ignored and holds every artefact with real data, including the fake store
  and all run output.
* `docs/migration/*` is counts-only. Customers appear as counts or `customer:<woo id>`.
* The pipeline never writes to `exports/*.json` originals; the delta source is a copy under
  `exports/migration/delta-source/`.
* Historical orders are archive-only (workstream 5) and are never loaded into Shopify. This
  pipeline does not read `exports/orders.json`.
