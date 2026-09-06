# ProSporter migration pipeline (CLNT-305)

Repeatable, deterministic WooCommerce → Shopify migration pipeline plus its dry-run
evidence. The default load target is a file-backed fake Admin API, so `run.py` makes no
network calls. The client store (`prosporter.myshopify.com`) exists, Admin access is in
`shopify_admin.py`, and the live loader (`shopify_target.py`) is verified against it.

Companion documents: **[error-recovery.md](error-recovery.md)** (every failure class the
loader can hit and exactly how a rerun recovers) and
**[cutover-runbook.md](cutover-runbook.md)** (ordered rehearsal and cutover steps,
rollback, and the API-call-derived time estimates).

Historical orders are not loaded into Shopify; they are delivered as a CSV archive built
by `scripts/migration/archive.py` — see **[archive.md](archive.md)**.

Everything in `docs/migration/` is derived and PII-free. Every artefact that contains
real customer or catalog data is written under `exports/` (git-ignored) and never leaves it.

## Stages

| Stage | What it does | Output |
|---|---|---|
| `extract` | Reads `exports/*.json`, checks every required entity is present, records the snapshot time from `exports/_manifest.json`. No network. | `source-summary.json` |
| `transform` | Applies execution-plan section 7 normalization and the approved IA, emits Shopify-shaped JSONL. Also extracts the WordPress images embedded in page/article bodies (CLNT-323). | one `.jsonl` per record type |
| `load` | Upserts every record into the target in the plan's load order. | `load-result.json`, the fake store, `mapping.json` |
| `reconcile` | Field-level source-vs-target comparison for every item in the plan's dry-run reconciliation list. | `reconciliation.json`, `docs/migration/reconciliation-latest.md`, `docs/migration/exception-register.csv` |
| `all` | extract → transform → load → reconcile in one process. | all of the above plus `run-manifest.json` |
| `prove` | Runs `all` twice on identical inputs, then once on a controlled delta, and diffs the fake store each time. | `docs/migration/idempotency-proof.md`, `exports/migration/proof.json` |
| `publish` | Live only, after QA. Publishes every ledger Product and Collection to a named publication and, with `--activate-published`, sets ACTIVE the products whose source status was `publish`. Dry run by default. | `<store>/publish-result.json`, `run-manifest.json` |

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

# publish stage (live only; dry run by default, see "Publish stage" below)
python3 scripts/migration/run.py publish --store exports/migration/live-store \
    --publication "ProSporter Dev"

# read-only ledger-vs-store verification
python3 scripts/migration/shopify_target.py verify --store exports/migration/live-store

# tests
python3 -m unittest discover -s scripts/migration/tests
```

Flags: `--source` (export directory, default `exports/`), `--target` (`fake` default,
`shopify` for the live Admin API), `--store` (store/ledger directory),
`--reset-store` (load from scratch; fake target only), `--no-docs` (skip the committed reports),
`--fail-on-critical` (exit 2 when unresolved critical exceptions remain — the quality gate),
`--live` (required by `--target shopify` and by the publish stage), `--skip-types`,
`--only-types` (load these record types and nothing else), `--only-products`. Publish-stage only: `--publication`, `--activate-published`, `--dry-run`.

Python 3.11+, standard library only. Deterministic: the same inputs produce byte-identical
JSONL, so two runs can be diffed.

## Run layout

```text
exports/migration/
  <run-id>/
    run-manifest.json        run id, pipeline commit, source snapshot, API version, target, counts
    source-summary.json      source-side counts
    products.jsonl  variants.jsonl  media.jsonl  collections.jsonl  metafields.jsonl
    metafield_definitions.jsonl  pages.jsonl  articles.jsonl  body_media.jsonl
    customers.jsonl
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

### Metafield definitions

Each `metafield_definitions.jsonl` record carries `namespace`, `key`, `type`, `name`,
`owner_type`, plus `description`, `pin` and `validations`. The types are fixed by the
storefront and never change; `description`, `pin` and `validations` exist so the fields are
usable by hand in the Shopify admin.

| Definition | Type | Pinned | Choices |
|---|---|---|---|
| `prosporter.surface` | `single_line_text_field` | yes | `beach`, `indoor` |
| `prosporter.club` | `list.single_line_text_field` | yes | `inner-west-volley`, `provolley-academy`, `teamwear` |
| `prosporter.gender` | `list.single_line_text_field` | yes | `Men`, `Unisex`, `Women` |
| `prosporter.size_guide` | `single_line_text_field` | yes | free text |
| `prosporter.personalisation` | `json` | yes | free text (JSON) |
| `migration.woo_id` | `single_line_text_field` | **no** | free text |

`validations` is a list of `{name, value}` pairs. The only one used is `choices`, whose
value is a **JSON array string** (`"[\"beach\",\"indoor\"]"`); 2026-07 supports it on
`single_line_text_field` and `list.single_line_text_field` (confirmed against
`metafieldDefinitionTypes.supportedValidations` on the client store).

The choice lists are **derived, not typed twice**: `transform.SURFACE_CHOICES` and
`CLUB_CHOICES` come from `normalize.SURFACE_COLLECTIONS` / `CLUB_COLLECTIONS`, and
`GENDER_CHOICES` from the range of `normalize.GENDER_SYNONYMS` — the same mapping that
populates the values. Before emitting a value the transform checks it against its choice
list; anything outside it is dropped and raised as `metafield_value_outside_choices`
(high, `purpl`) rather than loaded as a metafield Shopify would reject. All 394 values
already on the store are inside these lists.

Storefront access is unchanged: `PUBLIC_READ` for `prosporter.*`, `NONE` for `migration.*`.

#### What a merchant sees in the admin

Pinned definitions appear directly on the product form (Products → a product →
**Metafields**) instead of behind **Show all**, in definition order. With the `choices`
validation, `Playing surface` renders as a single-select dropdown and `Club or team` and
`Gender` as multi-select lists — no free typing, so a hand-added product cannot invent a
club handle the storefront has no collection for. Each field shows its one-line
description underneath. `migration.woo_id` stays unpinned and off the form (still visible
under **Show all**) and its description says it is set by the migration and must not be
edited.

## Mapping manifest

`exports/migration/fake-store/mapping.json` is the anti-duplication key. Identity per
resource:

| Resource | Identity key | Why |
|---|---|---|
| Product, Collection, Page, Article | `handle` | stable and human-checkable |
| ProductVariant, InventoryItem | `woo:<variation id>` | **SKUs are not unique in the source** (6 SKUs are shared by up to 19 variations), so SKU cannot be the identity |
| MediaImage | `<product handle>:<original url>` | one product can reuse an image |
| File (body image) | `<original url>` | one file, however many pages embed it |
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
collection membership, tags and metafields → body-image files → pages → articles →
customers → discounts). Body-image files come before pages on purpose: the page body is
rewritten to the CDN URLs those uploads produced.
Redirects (step 9) belong to the redirects workstream. Final publication to a sales
channel (step 10) is never part of a load: it is the separate `run.py publish` stage,
run after QA (see "Publish stage" below).

### What is stubbed and why

`FakeShopifyTarget` is the only working target. It assigns `gid://shopify/<Resource>/<n>`
ids from a persisted counter, stores each object with a payload checksum, and on rerun
compares checksums so an unchanged record reports `unchanged` and keeps its id.

`ShopifyAdminTarget` raises `NotImplementedError` on construction. It exists so the real
implementation has a named home and a documented contract. Implement it against Admin API
`2026-07` using `shopify_admin.AdminClient`:

| Stage | Mutation |
|---|---|
| metafield definitions | `metafieldDefinitionCreate` / `metafieldDefinitionUpdate` |
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

### Admin API access (`shopify_admin.py`)

The migration app is a Shopify Dev Dashboard app ("ProSporter-migration") installed on the
client store. There is no long-lived token: `shopify_admin.get_token()` mints a 24-hour
token with the OAuth client credentials grant from `SHOPIFY_ADMIN_CLIENT_ID` /
`SHOPIFY_ADMIN_CLIENT_SECRET` in `.env.local` and caches it at
`exports/migration/.admin-token.json` (git-ignored, mode 600). `AdminClient.graphql()`
refreshes on 401 and backs off on `THROTTLED`; `AdminClient.mutate()` raises on `userErrors`.

```bash
python3 scripts/migration/shopify_admin.py doctor   # scopes, location, publications, counts
python3 scripts/migration/shopify_admin.py token    # force a fresh token (prints expiry only)
```

`doctor` fails when any of the required scopes are missing:
`write_products, write_inventory, read_locations, write_customers, write_discounts,
write_content, write_files, write_publications, write_metaobject_definitions, read_markets`.

Store facts recorded 2026-09-05: internal domain `ihuvab-u2.myshopify.com`, primary domain
`prosporter.myshopify.com`, AUD, Basic plan, one location ("Shop location",
`gid://shopify/Location/118425878893`), Headless publication "ProSporter Dev"
(`gid://shopify/Publication/327884112237`), no products, no product metafield definitions.

### Live target (`shopify_target.py`)

`ShopifyAdminTarget` is the real loader. It reuses the fake target's ledger (`store.json`,
`mapping.json`) so reruns are diffed locally and an unchanged record costs no API call, and
it resolves natural keys on the store (handle, code, email, `migration.woo_id`, option
values) before creating anything, so a fresh checkout cannot duplicate objects. Products are
created `DRAFT` and are not published to any channel. Failures are per record: they land in
`<store>/failures.json` and in the exception register as `load_failed`, and the record is
retried on the next run because it never entered the ledger.

```bash
# smoke test: two products, nothing customer-facing
python3 scripts/migration/run.py all --target shopify --live \
    --store exports/migration/live-store --skip-types customers,discounts,pages,articles \
    --only-products ace-unisex,nago --no-docs
# definitions only: apply a metafield-definition change and touch nothing else
python3 scripts/migration/run.py all --target shopify --live \
    --store exports/migration/live-store --no-docs \
    --skip-types collections,products,variants,media,variants_inventory,collection_membership,metafields,pages,articles,customers,discounts
# content only: body-image files, pages and articles (CLNT-323 re-run)
python3 scripts/migration/run.py all --target shopify --live \
    --store exports/migration/live-store --no-docs \
    --only-types body_media,pages,articles
# staging reset: delete everything the ledger created (dry run without --yes)
python3 scripts/migration/shopify_target.py purge --store exports/migration/live-store --yes
# QA only: make one product visible to the Headless storefront
python3 scripts/migration/shopify_admin.py publish --handle nago --publication "ProSporter Dev" --activate
```

`--live` is mandatory for `--target shopify`, `--reset-store` is refused for it, and the
live ledger must not be the fake-store directory. The ledger records the store domain and
refuses to run against a different store.

`--skip-types` takes record types, and `loader.LOAD_ORDER` has exactly thirteen; naming the
twelve that are not `metafield_definitions` (the command above) is the supported way to
apply a definition-only change: the loader visits no other resource, so no product,
variant, metafield or customer call is made. Definitions are idempotent against the ledger
checksum, so a rerun with nothing changed reports `unchanged` and costs zero API calls.

`purge` deletes ledger `MetafieldDefinition` rows with
`metafieldDefinitionDelete(deleteAllAssociatedMetafields: true)`, so it removes the 394
loaded values with the definitions. It is a staging reset only.

2026-07 Admin API behaviour the loader depends on (verified on the client store, 5 Sep 2026):

| Concern | What 2026-07 does | What the loader does |
|---|---|---|
| Collection membership | no `collectionAddProducts`; `CollectionInput` has no `products` | `productCreate/productUpdate(collectionsToJoin/collectionsToLeave)`; removals only for products in the ledger |
| Variants | `productVariantsBulkCreate` with `REMOVE_STANDALONE_VARIANT` deletes the *only* existing variant on every single-variant call | strategy `DEFAULT`; the auto-created variant is matched by option values or pruned in `finish()` if no source variant claimed it |
| Inventory | `inventorySetQuantities` requires `changeFromQuantity` and the `@idempotent(key:)` directive | reads the current available quantity, skips when equal, otherwise compare-and-sets with a UUIDv5 key derived from the exact change |
| Customer addresses | `CustomerInput` has no `addresses` | `customerAddressCreate` / `customerAddressUpdate(setAsDefault:true)` |
| Discounts | `customerSelection` replaced by `context: {all: ALL}` | as documented; category-restricted, excluded-product and free-shipping-plus-value coupons are failed with a decision message |
| Product media | `productUpdate(media:[...])`; variant images via `productVariantsBulkUpdate(mediaId)` once media is `READY` | one image per call, id found by diffing the product's media list; variant images attached in `finish()` after polling (90 s cap) |
| Page/article SEO | no `seo` on page/article inputs | `global.title_tag` / `global.description_tag` metafields |
| Body images | `fileCreate` is async: `image { url }` is null until `fileStatus` is `READY` | files upload first, then `file_urls()` polls `nodes(ids:)` in batches (90 s cap) before the first page is written |
| Metafield definitions | `MetafieldDefinitionInput` and `MetafieldDefinitionUpdateInput` both carry `description`, `pin: Boolean` and `validations: [MetafieldDefinitionValidationInput!]`; only the create input takes `type` | one `metafieldDefinitionCreate` or `metafieldDefinitionUpdate` per definition with pin, description and validations inline — `metafieldDefinitionPin` / `metafieldDefinitionUnpin` are never needed |

### Body-image rewrite (CLNT-323)

Migrated page and article bodies came straight out of WordPress, so they still pointed
at `https://prosporter.com.au/wp-content/uploads/...`. At cutover DNS moves that host to
Vercel and every one of those images 404s. The pipeline now moves the files to Shopify
and rewrites the HTML.

`scripts/migration/body_media.py` is the whole rule set — pure string work, no network,
no Shopify dependency — and it is used by all three stages that need it.

**Transform.** Every non-held page and article body is scanned for WordPress upload
references: `src`, the lazy-loader `data-src` variants, **every `srcset` candidate**, and
`<a href>` links into `wp-content/uploads` (size-guide PDFs and the like). The hosts are
*derived*, never hard-coded: the export manifest's `base` plus every host in
`media.json`, with `www.` normalised away, so `prosporter.com.au` and
`www.prosporter.com.au` are one origin and the synthetic fixtures work unchanged.

Each reference is then resolved back to one file:

* a `-WIDTHxHEIGHT` resized variant (`hero-768x512.jpg`) collapses onto the original
  (`hero.jpg`) **when the original is in `media.json`** — so the six references a single
  WordPress figure emits become one upload;
* when there is no original in `media.json` the URL is kept exactly as written, uploaded
  by URL anyway, and reported as `body_image_not_in_media_export` (medium, client) so the
  gap is visible rather than papered over;
* a source `media_head` status other than 200 holds the file out of the load
  (`body_image_unreachable`) and its references keep the WordPress URL.

The result is one `body_media.jsonl` record per unique file, carrying the raw spellings
that collapsed onto it in `variants`, and `content_type` (`IMAGE`, or `FILE` for PDFs).

**Load.** `body_media` loads as the Shopify resource `File` — generic **Shopify Files**
(Content → Files), not product media, because these images belong to page content and to
no product gallery. The live target uses `fileCreate`, then `file_urls()` polls
`nodes(ids:)` until each file is `READY` and has a CDN URL; the fake target synthesises a
deterministic `cdn.shopify.com` URL from the object's gid so the dry run is byte-stable.
The source-URL → CDN-URL map is stored in the ledger (`store.json` → `file_urls`), so a
rerun uploads nothing and re-derives the same map.

The page/article body is rewritten **at load time**, immediately before the
create-or-update — not in the transform, because the CDN URL only exists once the file is
uploaded, and because the ledger checksum must be taken over the body Shopify actually
receives. That is what makes it idempotent: a rerun that resolves the same URLs produces
a byte-identical body and reports `unchanged`, and a body that really moved reports
`updated`. A rewritten `<img>` loses its `srcset`/`sizes` when every candidate collapsed
onto the same file — Shopify serves one original, and a srcset listing that URL at five
widths would be a lie. Nothing outside `wp-content/uploads` is touched: ordinary
`prosporter.com.au` page links survive, because after the DNS move the Next.js storefront
serves them.

Usage metadata (`variants`, `references`, `reference_count` on the file;
`body_image_refs`, `body_image_sources` on the page) stays out of the ledger payload, so
editing one page never restamps a file's checksum.

**Reconcile.** Six checks land in `reconciliation-latest.md`:

| Check | Meaning |
|---|---|
| `body_image_references_in_source` | references found in bodies vs. references in bodies that are actually loaded (held functional pages carry the rest) |
| `body_image_unique_files` | unique files vs. files not held for unreachability |
| `body_image_files_uploaded` | files expected vs. `File` objects in the target |
| `body_image_unresolvable_sources` | resized variants with no original in `media.json` |
| `body_image_references_rewritten` | loadable references vs. references now on `cdn.shopify.com` |
| `wordpress_image_references_left_in_loaded_bodies` | **the gate: must be 0** — counted by re-reading the bodies out of the target |

`page_article_bodies_with_a_rewrite` reports how many page/article bodies changed.

Dry run on the 2026-09-05 snapshot (`run.py all --reset-store --no-docs`): 579 references
across 14 page bodies (0 articles, 0 `<a href>` links to uploads), 56 of them inside the
held WooCommerce functional pages; 523 loadable references collapsing to **46 unique
files**, all 46 uploaded, all 523 rewritten, 0 WordPress upload references left in any
loaded body. 7 of the 46 are resized variants with no original in `media.json`. A rerun
reports 2867 unchanged / 0 created / 0 updated.

`run.py prove` exercises the delta too: `delta.py` adds one `<img>` to the lowest-id
migratable page as its fifth controlled change, and the proof shows exactly one new
`File` and exactly one updated `Page`.

Once a live content load is clean, `https://prosporter.com.au` and
`https://www.prosporter.com.au` can be removed from `img-src` in
`src/lib/security-headers.ts` — that edit belongs to the storefront workstream.

### Publish stage (`run.py publish`)

Execution-plan step 10, and the only stage that makes the catalog visible. It is a
separate command on purpose: the load leaves everything DRAFT and unpublished, so a
catalog can be loaded and QA'd before a single shopper can see it.

```bash
# dry run (the default): print the plan, write nothing
python3 scripts/migration/run.py publish --store exports/migration/live-store \
    --publication "ProSporter Dev"

# apply it
python3 scripts/migration/run.py publish --store exports/migration/live-store \
    --publication "ProSporter Dev" --live

# apply it and set ACTIVE the products whose WooCommerce status was 'publish'
python3 scripts/migration/run.py publish --store exports/migration/live-store \
    --publication "ProSporter Dev" --live --activate-published

# a QA-sized slice (restricts products by handle and drops collections)
python3 scripts/migration/run.py publish --store exports/migration/live-store \
    --publication "ProSporter Dev" --live --only-products nago,ace-unisex
```

* Every Product and Collection in the ledger is published to the named publication with
  `publishablePublish`. The 2026-07 schema takes **one** publishable id per call (there
  is no list form and `PublicationInput` carries only `publicationId` / `publishDate`),
  so the stage batches several aliased `publishablePublish` fields into one document,
  10 per request, falling back to one request per object if a batch is rejected.
* `--activate-published` sets `status: ACTIVE` **only** where the record's
  `source_status` is `publish`. Products that were drafts in WooCommerce stay DRAFT.
* Idempotent: the live `resourcePublicationsV2` state and product status are read first
  (batched `nodes(ids:)`, 50 per request) and anything already correct is reported
  `unchanged` with no mutation. A ledger object that no longer exists on the store is
  reported `failed`, not recreated.
* Outcomes (`published` / `activated` / `unchanged` / `failed`) go to
  `<store>/publish-result.json` and into the run manifest under `publish`.
* `--live` is required to write; `--dry-run` forces a plan even when `--live` is passed.
  The stage refuses to run against the fake store or a ledger with no `store.json`.

### Verify (`shopify_target.py verify`)

Read-only comparison of a ledger with the live store. It never writes to Shopify.

```bash
python3 scripts/migration/shopify_target.py verify --store exports/migration/live-store
python3 scripts/migration/shopify_target.py verify --store exports/migration/live-store \
    --no-checksums --batch 25
```

Every ledger object is fetched by gid in batches with `nodes(ids:)` (50 per request) and
the report names: objects **missing** from the store, **products whose live variant
count differs** from the ledger's, media Shopify left in a non-`READY` state, and (unless
`--no-checksums`) products whose handle/title/status has **drifted** from the loaded
payload. A DRAFT→ACTIVE status difference is annotated rather than treated as damage —
that is what the publish stage and the QA helper do. Reports: `<store>/verify-result.json`
and `<store>/verify-report.md` (both under `exports/`, git-ignored). Exit code 1 when
anything is missing or a variant count differs. Only ids, handles, titles, statuses and
counts are fetched: Customer, Metafield, InventoryItem and DiscountCodeNode objects are
presence-checked and nothing about them is read, so no personal data can reach a report.

Smoke test result (run `live-smoke-4`): 70 objects (6 definitions, 10 collections, 2
products, 13 variants, 12 media, 13 inventory items, 10 memberships, 4 metafields), 0
failures; rerun 70 unchanged / 0 created. Note the store's default `frontpage` collection is
automated and picked up Ace Unisex by tag; the client decides whether to keep it.

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
