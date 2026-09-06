# Historical-order archive (Workstream 5)

Historical WooCommerce orders are **not** imported into Shopify. The complete order
history through the cutover date is delivered as a self-contained CSV archive that
opens in Excel or Google Sheets without WordPress, WooCommerce, Shopify or any
purpl solutions system, and it is part of the final handover.

`scripts/migration/archive.py` builds that archive from the raw export snapshot.
It is deterministic (same snapshot in, byte-identical CSVs out), stdlib-only, and
makes no network calls.

Like every other artefact built from `exports/`, the archive contains real customer
personal data. It is written under `exports/migration/` (git-ignored) and never
copied into `docs/` or git. Everything below is counts only.

## Generate

```bash
# default: exports/ -> exports/migration/archive/prosporter-woocommerce-archive-<snapshot date>
python3 scripts/migration/archive.py

# explicit source and destination
python3 scripts/migration/archive.py --source exports \
    --out exports/migration/archive/prosporter-woocommerce-archive-2026-09-05

# CI / no exports needed: 3 synthetic orders, 1 refund, 3 fake customers
python3 scripts/migration/archive.py --source scripts/migration/fixtures \
    --out exports/migration/archive/fixture-archive

# tests
python3 -m unittest discover -s scripts/migration/tests
```

Exit code `0` means every reconciliation metric matched or carries a written
explanation; `1` means an unexplained discrepancy is present; `2` means a required
source file is missing.

Source files read: `orders.json`, `refunds.json` (required), `customers.json`,
`payment_gateways.json`, `order_notes_sample.json`, `_manifest.json` (optional).

## Archive layout

```text
prosporter-woocommerce-archive-YYYY-MM-DD/
  README.md                  conventions, file list, known source gaps, handling rules
  manifest.json              provenance, per-file sha256/bytes/rows, summary counts
  checksums.sha256           sha256sum -c format, covers every file in the archive
  reconciliation.csv         source vs archive, one row per metric
  reconciliation.md          the same reconciliation as a readable report
  orders.csv
  order-lines.csv
  payments.csv
  refunds.csv
  refund-lines.csv
  fulfilments.csv
  fulfilment-lines.csv
  customers-reference.csv
  attachments/
```

File names follow the execution plan's required archive structure
(`docs/shopify-nextjs-migration-execution-plan.md`, Workstream 5).

Verify a delivered archive with:

```bash
cd prosporter-woocommerce-archive-YYYY-MM-DD && sha256sum -c checksums.sha256
```

## CSV conventions

| Rule | Value |
|---|---|
| Encoding | UTF-8 **with BOM** (`utf-8-sig`) so Excel opens it correctly by double-click |
| Format | RFC 4180: one header row, CRLF terminators, `csv.QUOTE_MINIMAL`, doubled `"` inside quoted fields |
| Dates | ISO 8601 with an explicit offset, e.g. `2026-08-24T12:47:12+00:00`. The source store's timezone is UTC and WooCommerce returned identical local and GMT values, so the GMT field is used and stamped `+00:00` |
| Money | plain decimal, two places, no symbol or thousands separator; currency in its own column |
| Nulls | an empty cell, never `NULL`/`N/A`/`0`. `0.00` always means a real zero |
| Join key | `order_number` (merchant-facing WooCommerce number) in every file; `order_id` (WordPress post id) is kept alongside for traceability |
| Formula injection | a text cell starting with `=`, `+`, `-`, `@`, tab or CR gets a leading apostrophe. Purely numeric cells (including negatives such as `-37.50`) are left untouched so they stay numeric in a spreadsheet |
| Column order | fixed and stable across runs; new columns are appended, never inserted |

## Column glossary

### orders.csv - one row per order

`order_number`, `order_id`, `parent_order_id`, `status` (WooCommerce status verbatim),
`currency`, `date_created`, `date_modified`, `date_paid`, `date_completed`,
`created_via`, `customer_id` (empty for guest checkout), `customer_note`
(customer-supplied note), `billing_*` and `shipping_*` (`first_name`, `last_name`,
`company`, `address_1`, `address_2`, `city`, `state`, `postcode`, `country`,
`phone`, plus `billing_email`; WooCommerce holds no shipping email),
`line_item_count`, `item_quantity`, `items_subtotal` (sum of line subtotals before
order-level discounts), `discount_total`, `discount_tax`, `shipping_total`,
`shipping_tax`, `fee_total`, `cart_tax`, `total_tax`, `order_total`,
`refunded_total` (sum of refunds against this order), `net_total`
(`order_total - refunded_total`), `coupon_codes`, `shipping_methods`,
`payment_method`, `payment_method_title`, `transaction_id`, `prices_include_tax`,
`order_key`.

### order-lines.csv - one row per order line

`order_number`, `order_id`, `line_id`, `line_type` (`line_item`, `shipping` or
`fee`), `product_id`, `variation_id`, `sku`, `product_name`, `parent_name`,
`variant` (customer-visible line options, e.g. `Size: M; Colour: Navy`; internal
`_`-prefixed plugin meta is dropped), `quantity`, `unit_price`, `line_subtotal`,
`line_discount` (`line_subtotal - line_total`), `line_total`, `line_tax`,
`currency`.

### payments.csv - one row per order

`order_number`, `order_id`, `payment_method` (gateway id), `payment_method_title`
(as shown to the customer), `gateway_method_title` (from `payment_gateways.json`),
`transaction_reference` (gateway reference; no card data is exported),
`amount`, `currency`, `payment_date`, `payment_status`
(`paid`, `partially-refunded`, `refunded`, `unpaid`, `cancelled`, `failed`,
`paid-date-not-recorded`), `refunded_total`, `net_amount`.

### refunds.csv / refund-lines.csv

`refund_id`, `order_number`, `order_id`, `refund_date`, `amount` (positive),
`currency`, `refund_type` (`partial`/`full` from WooCommerce meta), `reason`,
`refunded_by_user_id`, `refunded_payment` (whether the gateway was refunded),
`refund_line_count`. Line rows add `line_id`, `refunded_item_id` (the original
order line), `product_id`, `variation_id`, `sku`, `product_name`, `variant`,
`quantity` (negative, as WooCommerce records it), `line_subtotal`, `line_total`,
`line_tax`.

### fulfilments.csv / fulfilment-lines.csv

`order_number`, `order_id`, `fulfilment_status` (`fulfilled`,
`in-progress (<status>)`, `not-fulfilled (<status>)`, derived from the order
status), `fulfilment_date` (`date_completed`), `delivery_type`
(`pickup`/`shipped`/`not recorded`, derived from the shipping method id),
`shipping_method`, `shipping_method_id`, `carrier`, `tracking_number`,
`tracking_url` (all three empty - see gaps below), `item_quantity`,
`shipping_recipient_name`, `shipping_city`, `shipping_state`, `shipping_postcode`,
`shipping_country`. Line rows list the items each fulfilment covers.

### customers-reference.csv

Reference copy of the customer accounts the orders point at: `customer_id`,
`username`, `email`, `first_name`, `last_name`, `role`, `date_created`,
`is_paying_customer`, `billing_*`, `shipping_*`, `orders_in_archive`,
`order_total_in_archive`. Customer migration itself is Workstream 4; this file
exists so the archive can be read without another data source.

### reconciliation.csv

`metric`, `scope`, `source_value`, `archive_value`, `difference`, `notes`. Every
row where source and archive differ must carry a note; the generator fails
(exit 1) if one does not.

## Verification steps

1. `python3 -m unittest discover -s scripts/migration/tests` - 26 archive tests
   covering row counts against the source, checksum integrity, byte-identical
   reruns, formula-injection neutralisation, refund-to-order linkage, orphan rows,
   and total reconciliation.
2. `sha256sum -c checksums.sha256` inside the archive directory.
3. Open `reconciliation.md`; confirm **Unexplained discrepancies: 0** and that the
   order count matches the source store.
4. Open `orders.csv` in Excel and Google Sheets; confirm the header row, that
   accented characters render, and that no cell is evaluated as a formula.
5. Confirm `manifest.json` `record_counts` match the row counts in each CSV.

## Real-run summary (counts only, no personal data)

Snapshot `2026-09-05T04:13:43Z` from the live WooCommerce store.

| File | Rows |
|---|---:|
| orders.csv | 896 |
| order-lines.csv | 2,980 |
| payments.csv | 896 |
| refunds.csv | 110 |
| refund-lines.csv | 135 |
| fulfilments.csv | 896 |
| fulfilment-lines.csv | 2,167 |
| customers-reference.csv | 182 |
| reconciliation.csv | 31 |
| attachments/ | 0 files |

- Source orders **896**, archived orders **896**. Order ids 2394-6864, dates
  2024-02-12 to 2026-09-01. Single currency: AUD.
- Orders by status: completed 766, processing 56, pending 40, cancelled 21,
  refunded 9, failed 3, return-approved 1.
- Order lines: 2,167 product lines, 703 shipping lines, 110 fee lines.
- Money: gross line subtotal 107,768.76; discounts 21,505.82; shipping 2,396.50;
  tax 0.00; order total 83,347.14; refunds 1,065.49; net 82,281.65 (AUD).
- Payments: 821 paid, 18 partially refunded, 9 refunded, 35 unpaid, 10 cancelled,
  3 failed. 706 orders carry a gateway transaction reference.
- Fulfilments: 766 fulfilled, 66 in progress, 64 not fulfilled. Delivery type
  408 pickup, 294 shipped, 194 not recorded (no shipping line on the order).
- Orphan rows in every child file: **0**. Unexplained discrepancies: **0**.

## Known source gaps

- **No carrier or tracking numbers.** The WooCommerce store ran no shipment-tracking
  plugin. No order field, order meta key or shipping line in the export carries a
  consignment number, carrier name or tracking URL. `fulfilments.csv` therefore
  records what does exist - status, completion date, delivery type and shipping
  method - and leaves `carrier`, `tracking_number` and `tracking_url` empty. If
  tracking history is required it has to come from the carrier accounts or the
  store's transactional email archive.
- **No invoice or packing-slip attachments.** The export contains no document
  files. The only attachment-shaped field is the RMA plugin's
  `wps_wrma_exchange_attachment`, which holds a status stub with no file reference.
  `attachments/README.md` records what was checked and how to add PDFs later: drop
  them in as `<order_number>-<document-type>.pdf` and re-run the generator, which
  lists and checksums whatever it finds.
- **No internal order notes.** `order_notes_sample.json` is empty; the WooCommerce
  REST export includes no per-order note records. The customer-supplied note is
  archived as `orders.csv.customer_note`; admin notes would need a fresh pull from
  the source store.
- **Tax columns are zero.** Prices are GST-inclusive and no order carries
  `tax_lines`, so every tax column is `0.00`. This matches the source exactly and
  is recorded as an explained difference in the reconciliation.

## Delivery

The archive is personal data. Encrypt it in transit and at rest, send the
decryption secret through a separate channel, and obtain written receipt from the
client (execution plan, Workstream 5 rules).
