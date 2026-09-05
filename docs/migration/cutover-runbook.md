# ProSporter cutover runbook (CLNT-305)

Rehearsal and final cutover for the WooCommerce → Shopify migration. Every command is
copy-pasteable. Counts only; no personal data.

Two passes through the same runbook:

* **Rehearsal** — everything except customers, discounts and DNS, against the client
  store with the catalog left DRAFT and published only to the "ProSporter Dev" Headless
  publication. Reversible with `purge`.
* **Cutover** — the rehearsal's steps plus customers, discounts, redirects and DNS,
  with the shop in maintenance at the WooCommerce end so the source snapshot cannot
  move underneath the load.

## 0. Preconditions (all must be true before step 1)

| # | Precondition | How to check |
|---|---|---|
| 1 | Admin app healthy, all scopes granted | `python3 scripts/migration/shopify_admin.py doctor` exits 0 |
| 2 | API version pinned at `2026-07` | `doctor` output `api_version`, and `SHOPIFY_API_VERSION` in `scripts/migration/common.py` |
| 3 | Exactly one active location, online-fulfilling | `doctor` → `locations`: "Shop location" (`gid://shopify/Location/118425878893`) |
| 4 | The target publication exists | `doctor` → `publications` contains "ProSporter Dev" |
| 5 | A fresh source snapshot | `exports/_manifest.json` timestamp is from today; re-export if not |
| 6 | Dry run clean | `run.py all --fail-on-critical` exits 0 |
| 7 | Client decisions closed | see the checklist below |
| 8 | The ledger directory is the right one | never `exports/migration/fake-store`; the ledger records its store domain and refuses another |

**Client decisions that must be closed before a cutover load** (from
`README.md` → "Cutover-relevant open decisions", tracked in
`docs/migration/exception-register.csv`):

1. SKUs — confirm the generated `PS-<product>-<variation>` pattern, and supply real SKUs
   for the 6 duplicated values.
2. Prices — the variations with no price anywhere stay held unless prices are supplied.
3. `Condition` and `Number` attributes — variant option, line-item property, or dropped.
4. The Easy Product Bundles product — rebuilt manually, or excluded.
5. Duplicate WordPress pages — the canonical set.
6. Tax and GST treatment configured in Shopify (the source has zero tax rates).
7. Shipping rates configured (721 of 917 variations have no weight, so weight-based
   rates are impossible).
8. The store's automated `frontpage` collection — keep it, or empty it. It picks up
   migrated products by tag.
9. Marketing consent — every migrated customer is `NOT_SUBSCRIBED`; consent is never
   invented. Confirm the re-permission plan before any send.

## 1. Load the catalog and content

Products load **DRAFT** and are published to no channel. Nothing here is customer-facing.

```bash
# one run id for the whole cutover, so every artefact is traceable
RUN=cutover-$(date -u +%Y%m%dT%H%M%SZ)
STORE=exports/migration/live-store

# catalog + content, customers and discounts deliberately left out
python3 scripts/migration/run.py all --target shopify --live \
    --store "$STORE" --run-id "$RUN" \
    --skip-types customers,discounts --no-docs
```

Then, before anything else:

```bash
# 0 failures expected; anything here is a per-record failure to triage
python3 -c "import json;d=json.load(open('$STORE/failures.json'));print(d['count'])"

# read-only ledger vs store: missing objects, variant-count and field drift
python3 scripts/migration/shopify_target.py verify --store "$STORE"
```

`verify` exits non-zero if anything is missing or a variant count differs. Rerun the
load command to retry failures — records that failed are not in the ledger and are the
only ones re-created (see `error-recovery.md`).

## 2. QA on the Headless storefront

The catalog is still invisible. Expose a small sample first:

```bash
# one product, one collection, to the Dev publication
python3 scripts/migration/shopify_admin.py publish --handle nago \
    --publication "ProSporter Dev" --activate
python3 scripts/migration/shopify_admin.py publish --collection tops \
    --publication "ProSporter Dev"

# storefront-side smoke check (indexing lags ~1 minute)
python3 scripts/migration/storefront_check.py nago
```

QA checklist: option names and values, prices and compare-at prices, images (including
variant images), inventory quantities, collection membership, the `prosporter.*`
metafields the storefront reads, SEO title/description, page and article bodies.
`docs/migration/reconciliation-latest.md` is the field-level source-vs-target report;
`docs/migration/exception-register.csv` explains every count difference.

## 3. Publish the catalog

Only after QA signs off. The stage is a dry run by default and idempotent — it reads
`resourcePublicationsV2` and product status first and skips what is already right.

```bash
# 1. plan (default; writes nothing to Shopify)
python3 scripts/migration/run.py publish --store "$STORE" \
    --publication "ProSporter Dev" --run-id "$RUN-publish"

# 2. apply: publish every ledger product and collection to the publication
python3 scripts/migration/run.py publish --store "$STORE" \
    --publication "ProSporter Dev" --live --run-id "$RUN-publish"

# 3. apply and set ACTIVE the products whose WooCommerce status was 'publish'
#    (source drafts stay DRAFT, whatever the flag says)
python3 scripts/migration/run.py publish --store "$STORE" \
    --publication "ProSporter Dev" --live --activate-published --run-id "$RUN-publish"

# narrow it while QA is still running
python3 scripts/migration/run.py publish --store "$STORE" \
    --publication "ProSporter Dev" --live --only-products nago,ace-unisex
```

Flags: `--publication` (default "ProSporter Dev"), `--live` (required to write),
`--dry-run` (forces a plan even with `--live`), `--activate-published`,
`--only-products` (restricts to those product handles and drops collections).
Outcomes land in `<store>/publish-result.json` and in the run manifest as
`publish.counts` / `publish.outcomes` (`published` / `activated` / `unchanged` /
`failed`). Measured dry run against `exports/migration/live-store` on 5 Sep 2026:
**164 objects (154 products + 10 collections), publish=162, activate=134, unchanged=2,
missing=0** — the two unchanged objects are the ones the QA helper had already published,
and the 19 products that stay DRAFT are the ones whose WooCommerce status was `draft`
(135 of the 154 loadable products were `publish` at source).

For the production storefront, repeat step 3 against the live sales channel name once
the client confirms it.

## 4. Customers and discounts (cutover only, not the rehearsal)

Run these last, in the maintenance window, so the customer set is final and no coupon
is live before the store is.

```bash
python3 scripts/migration/run.py all --target shopify --live \
    --store "$STORE" --run-id "$RUN-customers" \
    --skip-types metafield_definitions,collections,products,variants,media,variants_inventory,collection_membership,metafields,pages,articles \
    --no-docs
```

Customers arrive with `NOT_SUBSCRIBED` marketing consent — the source has no consent
field. Do not send to them until the client's re-permission plan is agreed. Customers
do not get Shopify invitations from the load; account activation is a separate,
client-approved send.

## 5. Redirects

Owned by the redirects workstream (`urlRedirectCreate`, execution plan step 9). Every
WooCommerce product, category, page and post URL needs a redirect to its Shopify
equivalent; `<run-id>/id_map.jsonl` is the source-to-destination map to build them
from. Load and verify redirects **before** DNS, so the first request on the new
domain already resolves.

## 6. DNS

Last. Once the storefront serves the published catalog and redirects are in place:

1. Lower the TTL on the existing records 24–48 h beforehand.
2. Put WooCommerce into maintenance / read-only.
3. Take the final source export and rerun steps 1–4 (the load is a diff — it only moves
   what changed since the rehearsal).
4. Point the domain at the storefront host.
5. Watch: 404s, checkout, the storefront's Shopify request logs (`src/lib/log.ts`).
6. Keep the WooCommerce origin reachable but unindexed until redirects are verified.

## Rollback

**Rehearsal / staging.** One command deletes everything the ledger created (discounts,
customers, articles, pages, products, collections, blogs we created, metafield
definitions) and then removes the ledger files:

```bash
python3 scripts/migration/shopify_target.py purge --store "$STORE"        # plan
python3 scripts/migration/shopify_target.py purge --store "$STORE" --yes  # execute
```

It only touches objects in the ledger, so merchant-created objects are safe. If any
delete errors, the ledger files are kept so nothing is orphaned.

**Production, after cutover.** Do **not** purge — customers may have ordered. Roll back
by visibility, not by deletion, in this order:

1. **Unpublish**, don't delete: remove the catalog from the sales channel
   (`publishableUnpublish`) and/or set products back to DRAFT. `<store>/publish-result.json`
   lists exactly which ids the publish stage published and which it activated, so the
   set to reverse is known.
2. **Revert DNS** to WooCommerce (this is why the TTL was lowered).
3. **Disable the migrated discounts** — 5 codes, by code, in the Shopify admin.
4. Delete only objects that provably have no orders, no customer and no external link:
   collections and pages/articles first, products last, and never a customer record.
5. Keep the ledger. It is the only map from WooCommerce ids to Shopify gids; without it
   a second attempt cannot avoid duplicates.

## Time estimates

Derived from the record counts in `exports/migration/2026-09-05a/*.jsonl` (products 161,
variants 923, media 480, metafields 417, collections 10, pages 30, articles 15,
customers 178, discounts 5; held records are excluded, leaving products 154, variants
782, media 469, metafields 394, pages 22) and the loader's actual call pattern.

### Admin API calls, first full load (empty ledger)

| Stage | Records | Calls per record | Calls |
|---|---:|---|---:|
| metafield definitions | 6 | lookup + create | 12 |
| collections | 10 | lookup + create | 20 |
| products | 154 | lookup + create | 308 |
| variants | 782 | 1 `productVariantsBulkCreate` each, + 1 variant list per product (132) | 914 |
| placeholder prune (`finish`) | 132 products | 1 variant list each + 1 delete for the 100 multi-variant products | 232 |
| media | 469 | 1 `productUpdate` each, + 1 media list per product (114) | 583 |
| variant images (`finish`) | 165 links | status poll per product + 1 bulk update | 200–400 |
| inventory | 782 | 1 `inventoryItemUpdate` each + 761 level reads + 623 quantity sets | 2,166 |
| collection membership | 10 | 1 members read each + 240 `productUpdate` joins | 250 |
| metafields | 394 | 1 `metafieldsSet` | 394 |
| pages | 22 | lookup + create | 44 |
| articles | 15 | 1 blog lookup + lookup + create each | 31 |
| customers | 178 | lookup + create; 83 also read + write an address | 522 |
| discounts | 5 | lookup + create | ≤10 |
| **Total** | | | **≈ 5,800** |

Call it **5,400–6,500** once phone-number retries and a few throttle replays are
allowed for. A rerun with no source change is **0 API calls** for the load itself — the
ledger checksums short-circuit every upsert (`live-smoke-3`: 69 unchanged).

### Measured latency

Read-only measurements against `prosporter.myshopify.com` on 5 Sep 2026:

* `{ shop { name } }` × 6: 0.323, 0.325, 0.328, 0.339, 0.402, 0.422 s.
* Batched `nodes(ids:)` with the publication fragments: 0.39–0.41 s for 2 and for 12 ids
  — the batch size barely matters, the round trip dominates.
* `verify` over the smoke ledger: 478 ids in 10 calls, a few seconds end to end.
* `live-smoke-3` (an all-unchanged rerun over the full 161-product source) finished
  **2 s** after `live-smoke-2`'s manifest, which is the pipeline's own
  extract + transform + reconcile cost with zero API calls. Locally, `extract` alone is
  0.18 s. Pipeline overhead is therefore negligible next to the network.

Writes are heavier than a trivial read. Taking **0.35 s** as the measured floor and
**0.8 s** as a conservative per-mutation figure gives the range below. The mutation
figure is an assumption, not a measurement: the smoke runs' manifests record only the
time each run *finished*, which is not enough to divide by call count, and no write was
issued while preparing this estimate.

### Rate limits (state the assumption)

Shopify's GraphQL Admin API is a leaky bucket of **cost points**, not requests. The
documented Basic-plan figure is a 1,000-point bucket restoring at 50 points/s. The
throttle status this store actually returned on 5 Sep 2026 is:

```
maximumAvailable 2000, currentlyAvailable 1999, restoreRate 100.0
```

so the store is running at 2,000 points / 100 points per second. Both are used below.
Assume a mean of **8 cost points per call** (a trivial read costs 1; single-object
mutations are typically ~10).

| Bound | At 100 pts/s (measured) | At 50 pts/s (documented Basic) |
|---|---:|---:|
| 5,800 calls × 8 points | 46,400 points → **≈ 8 min** | **≈ 15 min** |

The rate limit is **not** the binding constraint. Round-trip latency is:

| Bound | Calls | Per call | Wall clock |
|---|---:|---|---|
| Optimistic | 5,400 | 0.35 s | ≈ 32 min |
| Expected | 5,800 | 0.5 s | ≈ 48 min |
| Conservative | 6,500 | 0.8 s | ≈ 87 min |

Add up to 90 s of media-processing polling per run (`MEDIA_READY_WAIT_SECONDS`), and
allow for a second pass to attach any images that were still processing.

**Plan for 45–90 minutes for the first full load, single-threaded, with a worst case of
2 hours if throttling and retries bite.** Budget for it:

| Step | Estimate |
|---|---|
| Preconditions and dry run | 5–10 min |
| 1. Catalog + content load | 45–90 min |
| 1b. `verify` | < 1 min (10 API calls) |
| 2. QA | client-driven; allow half a day |
| 3. Publish stage | ≈ 40 calls (164 objects: 4 state reads, then aliased mutations 10 per document) → **under 1 minute** |
| 4. Customers + discounts | ≈ 530 calls → 5–10 min |
| 5. Redirects | redirects workstream |
| 6. DNS | TTL-bound; propagation window agreed with the client |
| Rerun after the final export (a diff) | minutes, proportional to what changed |

The rerun figure is the important one for the maintenance window: because the loader is
a diff and not a replay, the cutover-day run only touches what moved since the
rehearsal. The long load happens during the rehearsal, not during the window.
