# Migration load: failure classes and recovery (CLNT-305)

How the live loader (`scripts/migration/shopify_target.py`) behaves when something
goes wrong, and exactly what a rerun does about it. Counts only; no personal data.

The whole recovery model rests on one invariant:

> **A record enters the ledger only after the Admin API has confirmed the write.**
> Anything that failed is therefore absent from `store.json`, and the next run treats
> it as new work. Reruns are safe because they are diffs, not replays.

`upsert()` in `shopify_target.py` implements it: on a `ShopifyAdminError` it records
the failure and returns `(None, "failed")` *without* touching `self.state["objects"]`;
on success it writes the ledger entry and calls `_flush()` immediately, so the ledger
on disk is never more optimistic than the store.

## The artefacts

| File | Where | What it holds |
|---|---|---|
| `<store>/store.json` | ledger dir under `exports/` | every confirmed object: identity key → `{id, checksum, payload}`. Flushed after **every** successful write. |
| `<store>/mapping.json` | ledger dir | source key → gid, plus the SKU / woo-id indexes. Written by `finish()`. |
| `<store>/failures.json` | ledger dir | `{store, api_version, count, failures:[{resource, key, message}]}` for the run that just ended. Rewritten each run, so an empty list means the last run was clean. |
| `<run-id>/exceptions.jsonl` | run dir | the same failures as structured exceptions, `code: load_failed`, `severity: high`, `owner: purpl`, `retry_status: auto-retryable`. |
| `<run-id>/load-result.json` | run dir | per-record outcome (`created` / `updated` / `unchanged` / `failed`) and the `stats` totals. |
| `<store>/verify-result.json`, `verify-report.md` | ledger dir | read-only ledger-vs-store comparison (`shopify_target.py verify`). |

## Failure classes

### 1. Per-record Admin API error (`userErrors` or a GraphQL error)

The most common class: a rejected input, a value Shopify will not accept (an
unparseable phone number, a discount shape `discountCodeBasic` cannot express), or a
dependency that was not loaded (a variant whose product failed earlier).

* `AdminClient.mutate()` raises `ShopifyAdminError` on any `userErrors` entry.
* `upsert()` catches it, increments `stats["failed"]` and the resource's `failed`
  bucket, appends to `self.failures`, and returns `(None, "failed")`.
* `loader.load()` turns that into a `load_failed` exception carrying the message.
* **The load continues.** One bad record never aborts the run.
* Recovery: fix the cause (usually a source-data or decision issue named in the
  message), rerun the same command. The record is not in the ledger, so it is created;
  everything else matches its checksum and reports `unchanged` at zero API cost.
* Some messages are deliberate refusals rather than bugs — a coupon restricted to
  WooCommerce categories, a coupon with excluded products, a product whose live
  options differ from the source. Those need a client decision, not a retry, and the
  exception register carries them.

A few handlers retry in place before failing: `_customer` strips a phone number
Shopify rejects (recording it in the customer note) and retries once, and
`_customer_address` does the same for the address phone.

### 2. Media stuck or FAILED

Shopify processes uploaded images asynchronously. Variant images can only be attached
once the media object is `READY`, so `finish()` polls (`_attach_deferred_variant_media`,
5-second interval, `MEDIA_READY_WAIT_SECONDS = 90` cap).

* Media that reports `FAILED`, or is unknown to the product, is failed with the media
  key and the status.
* Media still processing when the 90-second cap expires is failed with
  *"media still processing after wait; rerun to attach"*.
* Either way the **image itself is in the ledger** (the `MediaImage` upsert succeeded);
  only the variant-image link is missing.
* Recovery: rerun. The `MediaImage` record is `unchanged`, and the variant-image link is
  re-queued and attached because the media has finished processing by then.
* Source images the pipeline already knows are unreachable (`reachable: false`, e.g.
  HTTP 404 at the WordPress end) fail immediately without an API call. Those need the
  client to supply the file; the run's exception register names the product.

### 2b. Body-image file stuck, FAILED, or unresolvable (CLNT-323)

Page and article body images are uploaded to Shopify Files (`fileCreate`) before the
pages that embed them, and the body HTML is rewritten to the CDN URL the upload produced.
`fileCreate` is asynchronous too, so `file_urls()` polls `nodes(ids:)` until each file is
`READY` (3-second interval, the same `MEDIA_READY_WAIT_SECONDS = 90` cap) *before* the
first page is written.

* A file Shopify reports as `FAILED` is a class 1 per-record failure (`resource: File`)
  and never enters the ledger, so the next run re-uploads it.
* A file still processing at the cap is **warned**, not failed: it is in the ledger with
  its gid, and the bodies that reference it keep their WordPress URL for this run. The
  next run finds the ledger entry, resolves the CDN URL through `file_urls()`, rewrites
  the body and reports the page `updated`. Nothing is uploaded twice.
* A run interrupted between the upload and the ledger flush is recovered by
  `_find_uploaded_file()`, which matches an unclaimed file on the store by filename stem
  rather than uploading a duplicate.
* A source image the pipeline already knows is unreachable (`reachable: false`) is held
  out of the load with `body_image_unreachable`, and its references stay as WordPress
  URLs — visible in the `wordpress_image_references_left_in_loaded_bodies` reconciliation
  check, which is the cutover gate.
* A resized variant with no original in `media.json` is reported as
  `body_image_not_in_media_export` (medium, client) and uploaded by its own URL; if
  Shopify cannot fetch it the upload fails as class 1 and the client has to supply the file.

### 3. Rate limiting (`THROTTLED`)

Shopify's GraphQL Admin API is a leaky bucket of cost points, not a request count.

* `AdminClient.graphql()` detects `extensions.code == THROTTLED`, reads
  `extensions.cost.throttleStatus.restoreRate` and `requestedQueryCost` from the same
  response, sleeps `cost / restoreRate` (clamped to 1–20 s) and retries, up to
  `THROTTLE_RETRIES = 5`.
* HTTP 429 / 502 / 503 / 504 back off exponentially (2, 4, 8, 16, 20 s) for the same
  number of attempts.
* Only after five attempts does the call raise, and then it degrades to a class 1
  per-record failure — the run keeps going and the record is retried next run.
* The loader is single-threaded and issues one request at a time, which is why the
  measured full-load cost sits far below the store's restore rate (see the cutover
  runbook's call-count table).

### 4. Token expiry

Tokens are minted with the client-credentials grant and live 24 hours; a full catalog
load is far shorter than that, but an interrupted-and-resumed run can straddle expiry.

* `get_token()` refreshes when under 5 minutes remain (`REFRESH_MARGIN_SECONDS`).
* If a call still gets HTTP 401, `AdminClient.graphql()` mints a fresh token once and
  replays the request transparently. The record does not fail.
* If the app is uninstalled or its secret rotated, minting fails with a clear message
  and no secret in the text. Recovery: fix `.env.local`, run
  `python3 scripts/migration/shopify_admin.py doctor`, rerun the load.

### 5. Interrupted run (Ctrl-C, crash, laptop asleep, network drop)

* The ledger is flushed after every successful write, so it is durable at the record
  level, not the run level.
* Rerunning the same command resumes: everything already in the ledger matches its
  checksum and reports `unchanged` **without an API call**, and the load picks up where
  it stopped.
* Two things are only done in `finish()` and are therefore skipped by an interrupted
  run: pruning Shopify's auto-created placeholder variants and attaching variant
  images. Both are idempotent and are completed by the next clean run — which is why
  `verify` can legitimately report a variant-count difference of one while a load is
  still in flight.
* `mapping.json` is also written by `finish()`, so after an interruption it can lag
  `store.json`. `store.json` is the source of truth; `mapping.json` is regenerated on
  the next run.

### 6. Starting over (staging only)

`python3 scripts/migration/shopify_target.py purge --store <ledger> --yes` deletes
every object the ledger created, in reverse dependency order, then removes
`store.json`, `mapping.json` and `failures.json`. Without `--yes` it prints the plan.
Objects already gone from the store count as deleted. If any delete errors the ledger
files are kept, so nothing is orphaned silently. **This is a staging reset. Never run
it against a production store after cutover** — see the rollback section of the
cutover runbook.

## Proof: the retry test

`scripts/migration/tests/test_pipeline.py::FailureRecovery` drives the real
`ShopifyAdminTarget` against a stub Admin client that fails the first mutation for one
of three collections and succeeds afterwards:

| Run | Result |
|---|---|
| 1 | `created = 2`, `failed = 1`; ledger holds `collection-a`, `collection-c`; `collection-b` is **absent**; one `load_failed` exception naming `collection-b`; `failures.json` count 1; `store.json` on disk already shows the two successes (flush-per-write). |
| 2 | the stub receives exactly **one** create mutation, for `collection-b`: `created = 1`, `unchanged = 2`, `updated = 0`, `failed = 0`, `failures.json` count 0, and the two earlier collections keep their destination ids. |

That is the whole recovery contract in one test: the failure is isolated, the retry is
exactly the failed record, and nothing else is touched.

## Evidence from the live smoke runs

Four runs against `prosporter.myshopify.com` (ledger `exports/migration/live-store`,
git-ignored), two products and their dependants. Counts from each run's
`load-result.json`:

| Run | created | updated | unchanged | failed | What it proves |
|---|---:|---:|---:|---:|---|
| `live-smoke-1` | 57 | 0 | 0 | 19 | Per-record isolation. 13 `InventoryItem` and 6 `MediaImage` failures (the 2026-07 `inventorySetQuantities` compare-quantity/idempotency-key shape, and one image per `productUpdate`) did not stop the other 57 objects loading. |
| `live-smoke-2` | 69 | 0 | 0 | 1 | A purge-and-reload from scratch once the 2026-07 input shapes were fixed. 69 of 70 objects created; one inventory record still failed, and stayed out of the ledger. |
| `live-smoke-3` | 0 | 0 | 69 | 1 | A rerun with no source change: **every** ledger object reported `unchanged`, so zero Admin write calls. The one absent record was retried — and failed again, as it must until the cause is fixed. |
| `live-smoke-4` | 1 | 0 | 69 | 0 | The cause was fixed. The run created **exactly** that one record and left the other 69 alone. **70 objects, 0 failures.** |

Read across runs 2–4: failures 1 → 1 → 0, and creates 69 → 0 → 1. Nothing is ever
created twice; the ledger converges on the 70 objects `live-smoke-4` holds (6
definitions, 10 collections, 2 products, 13 variants, 12 media, 13 inventory items, 10
memberships, 4 metafields). Run 3 is the idempotency evidence — an unchanged catalog
costs nothing — and run 4 is the recovery evidence, on the real store, of the same
behaviour the `FailureRecovery` unit test pins down.
