# ProSporter authenticated source audit (CLNT-169)

Snapshot taken 5 September 2026 against `https://prosporter.com.au` using a read-only WooCommerce REST key and a WordPress application password. Raw exports live in the git-ignored `exports/` folder because they contain customer and order data. Everything in this folder is derived from them and contains no personal data.

Regenerate with:

```bash
python3 scripts/audit/woo_audit.py          # export + report
python3 scripts/audit/woo_audit.py report   # report only, from existing exports/
```

## Files

| File | Purpose |
|---|---|
| `source-inventory.json` | Authenticated counts for every entity, taxonomy values, order/customer/coupon/shipping/tax/payment snapshot, discrepancies vs public API and repo mock |
| `plugin-and-integration-register.md` | All 49 active plugins with data-fingerprint evidence and proposed disposition; payment/refund/tracking data locations |
| `data-quality-report.csv` | 1,709 rows, severity-ranked, one row per defect with entity ID, owner and disposition column |
| `url-inventory.csv` | 318 URLs from the Yoast sitemaps plus every product/page/post permalink, with proposed destination and redirect type |
| `media-inventory.csv` | 932 attachments with dimensions, size, alt text, reachability and the products that use each |
| `content-inventory.csv` | 45 pages/posts with status, word count, embedded images, shortcodes, Elementor usage and Yoast fields |

## Headline numbers

| Entity | Authenticated | Public API (3 Sep) | Repo mock |
|---|---:|---:|---:|
| Products (any status) | 161 | 141 | 94 |
| Products published | 141 | 141 | |
| Products draft | 20 | | |
| Variations | 917 | 861 refs | 470 size entries |
| Orders (Feb 2024 to Sep 2026) | 896 | | |
| Customers (role customer) | 178 | | |
| Coupons | 5 | | |
| Pages / posts | 30 / 15 | 27 / 15 | |
| Media attachments | 932 (231 MB) | | |
| Sitemap URLs | 292 | | |

## Findings that need a decision or an owner

1. **219 variations have no SKU** across 45 products, and 11 SKUs are duplicated (worst: `PROT00SEM-1` used 20 times). Shopify requires unique SKUs for inventory tracking. Decision: generate SKUs from a pattern, or client supplies them.
2. **56 variations have no regular price** (Modena Volley Jersey, Stivo Pants, Brione Tracksuit and five others). They are purchasable only through the parent's price fallback. Owner: client to confirm prices.
3. **44 published products have no images.** Owner: client.
4. **96 orders are open** (56 processing, 40 pending), some dating back to April 2025. These need to be closed or re-snapshotted at cutover. Owner: client.
5. **Payments are Stripe only.** 679 of 896 orders went through the Stripe gateway (card, Apple Pay, Google Pay, Link). WooPayments is installed but has processed zero orders. 32 orders used Ezidebit and 14 a wallet plugin that is no longer active. Feeds CLNT-170.
6. **PPOM add-on fields** (`is_junior_team`, `plays_senior`, `confirmed_number`, `if_provolley_player`, `select_your_junior_team`) exist on 126 order lines, plus three Flexible-Checkout-style fields for jersey numbers and team on 69 orders. Team-kit personalisation must be rebuilt on Shopify as line-item properties. Feeds CLNT-171 and CLNT-172.
7. **RMA plugin data** on 217 orders (exchanges and refunds). Archive only; Shopify has no equivalent. Feeds CLNT-178.
8. **Product attributes exceed Shopify's 3-option limit** on 2 products (4 attributes). Attribute names are inconsistent: both `Color` and `Colour`, plus `Condition`, `Number`, `Hats`, `Gender`. Normalise per plan section 7.
9. **One bundle product** (Easy Product Bundles) with 73 historical lines. Manual recreation.
10. **Content duplicates**: `cart-2`, `checkout-2`, `my-account-2`, `blog-2`, `wishlist-2`, `1687-2` pages, plus 3 draft pages. Owner: client to confirm canonical set.
11. **26 of 45 pages/posts are Elementor layouts.** Copy migrates as HTML; layouts are re-authored in Next.js.
12. **Yoast Premium redirects are not exposed via REST.** Export manually from SEO → Redirects and merge into `url-inventory.csv`.
13. **Tax**: prices include tax, tax calculation on, but zero tax rates configured. Confirm GST handling before Shopify tax setup.
14. **Shipping**: AU zone with free shipping, $12 flat rate and local pickup; NZ zone with $25 flat rate. No shipping classes, and 721 of 917 variations have no weight.
15. **Customers**: 178 accounts, 97 without any address, 0 duplicate emails, no marketing-consent field found. 773 of 896 orders were guest checkouts (428 unique guest emails).
16. **Media**: 716 of 932 images have no alt text. All 932 files are reachable.

## Excluded from migration by data evidence

No product, order or coupon carries data from: Mirakl Connect, SellKit, NextMove, Barcode Scanner, StoreAgent AI, Coupon Generator, PDF Coupons, Wishlist, Quick View, Infinite Scroll, Instagram/Twitter widgets, LayerSlider, Autocomplete Address. See the register for the full list.
