# Plugin and integration register

Snapshot: 2026-09-05T04:13:43Z from `https://prosporter.com.au` (authenticated). 49 active plugins of 50 installed.

Usage evidence counts data fingerprints found in the authenticated export; a zero means no product, order, or coupon carries data from the plugin and it is a candidate for 'not migrated'.

| Plugin | Version | Usage evidence | Holds migratable data | Disposition |
|---|---:|---|---|---|
| Advanced Coupons for WooCommerce Free | 4.7.5 | 5 coupons (coupon rules) | yes | recreate as Shopify discounts; check unsupported rules |
| Advanced Order Export For WooCommerce | 4.1.0 | no data fingerprint | no | not migrated (confirm with client) |
| Akismet Anti-spam: Spam Protection | 5.7.2 | no data fingerprint | no | not migrated (confirm with client) |
| Autocomplete Address and Location Picker for WooCommerce | 1.2.2 | no data fingerprint | no | not migrated (confirm with client) |
| Barcode Scanner with Inventory & Order Manager - (business) | 1.10.2 | no data fingerprint | no | not migrated (confirm with client) |
| Bridge Core | 3.3.4.8 | no data fingerprint | no | not migrated (confirm with client) |
| Code Snippets | 3.9.6 | no data fingerprint | no | not migrated (confirm with client) |
| Contact Form 7 | 6.1.7 | 3 forms (forms) | yes | rebuild in Next.js with server action / email provider |
| Easy Product Bundles for WooCommerce | 6.20.1 | 1 products (bundles) | yes | manual recreation; decide bundle approach |
| Elementor | 4.2.3 | 26 pages/posts built with Elementor | yes (layout) | content re-authored in Next.js; copy migrated as HTML/Markdown |
| Elementor Pro | 4.2.2 | 26 pages/posts built with Elementor | yes (layout) | content re-authored in Next.js; copy migrated as HTML/Markdown |
| Envato Market | 2.0.14 | no data fingerprint | no | not migrated (confirm with client) |
| Flexible Checkout Fields | 4.1.41 | 0 order meta keys (sum) (custom checkout fields) | no | installed but unused; not migrated |
| Flexible Checkout Fields PRO | 4.0.30 | 0 order meta keys (sum) (custom checkout fields) | no | installed but unused; not migrated |
| Flexible PDF Coupons for WooCommerce | 1.14.10 | no data fingerprint | no | not migrated (confirm with client) |
| Flexible Refund Order for WooCommerce Pro | 2.0.0 | no data fingerprint | no | not migrated (confirm with client) |
| Happy Elementor Addons | 3.23.1 | 26 pages/posts built with Elementor | yes (layout) | content re-authored in Next.js; copy migrated as HTML/Markdown |
| Jetpack | 16.1.2 | no data fingerprint | no | not migrated (confirm with client) |
| LayerSlider | 8.4.0 | no data fingerprint | no | not migrated (confirm with client) |
| Mirakl Connect Integration for WooCommerce | 1.0.8 | 0 order meta keys (sum) (marketplace sync) | no | installed but unused; not migrated |
| NextMove Lite - Thank You Page for WooCommerce | 2.24.0 | no data fingerprint | no | not migrated (confirm with client) |
| PPOM for WooCommerce | 34.0.8 | 126 line items (Product add-on fields) | yes | migrate as line-item properties / metafield-driven form |
| Product Filter for WooCommerce by WBW | 3.1.7 | no data fingerprint | no | not migrated (confirm with client) |
| Qi Addons for Elementor | 1.11 | 26 pages/posts built with Elementor | yes (layout) | content re-authored in Next.js; copy migrated as HTML/Markdown |
| Qi Addons for Elementor Premium | 1.10.1 | 26 pages/posts built with Elementor | yes (layout) | content re-authored in Next.js; copy migrated as HTML/Markdown |
| Qi Blocks | 1.5.2 | no data fingerprint | no | not migrated (confirm with client) |
| Qode Instagram Widget | 2.1.3 | no data fingerprint | no | not migrated (confirm with client) |
| QODE Optimizer | 1.2.2 | no data fingerprint | no | not migrated (confirm with client) |
| QODE Quick View for WooCommerce | 1.1.2 | no data fingerprint | no | not migrated (confirm with client) |
| Qode Twitter Feed | 2.0.4 | no data fingerprint | no | not migrated (confirm with client) |
| QODE Wishlist for WooCommerce | 1.2.8 | 0 order meta keys (wishlists) | no | installed but unused; not migrated |
| Return Refund and Exchange for WooCommerce | 4.6.4 | 1291 order meta keys (sum) (RMA requests) | yes | archive; Shopify returns handled natively or via app |
| RMA Return Refund & Exchange for WooCommerce Pro | 5.6.2 | 1291 order meta keys (sum) (RMA requests) | yes | archive; Shopify returns handled natively or via app |
| SellKit - Funnel builder and checkout optimizer for WooCommerce to sell more, faster | 2.6.0 | 0 order meta keys (sum) (funnels/checkout) | no | installed but unused; not migrated |
| Site Kit by Google | 1.185.0 | no data fingerprint | no | not migrated (confirm with client) |
| StoreAgent AI for WooCommerce | 1.1.8 | no data fingerprint | no | not migrated (confirm with client) |
| Ultimate Infinite Scroll | 1.0.5 | no data fingerprint | no | not migrated (confirm with client) |
| UpdraftPlus - Backup/Restore | 1.26.7 | backup plugin | n/a | use for CLNT-168 verified backup |
| Variation Swatches for WooCommerce | 2.4.0 | 0 product meta keys (swatch display) | no | installed but unused; not migrated |
| WooCommerce | 11.0.1 | 161 products, 896 orders, 182 customers | yes | source of truth for migration |
| WooCommerce Coupon Generator | 1.3.0 | no data fingerprint | no | not migrated (confirm with client) |
| WooCommerce Stripe Gateway | 10.9.0 | 679 orders (payments) | yes | gateway decision (CLNT-170) |
| WooCommerce.com Update Manager | 1.0.3 | no data fingerprint | no | not migrated (confirm with client) |
| WooPayments | 11.0.1 | 0 orders (payments) | no | installed but unused; not migrated |
| WPC Product Bundles for WooCommerce | 8.6.4 | 1 products (bundles) | yes | manual recreation; decide bundle approach |
| YellowPencil | 7.6.7 | no data fingerprint | no | not migrated (confirm with client) |
| Yoast SEO | 28.3 | 923 product meta keys (sum) (SEO metadata) | yes | export to Shopify SEO fields / Next metadata |
| Yoast SEO Premium | 28.3 | 923 product meta keys (sum) (SEO metadata) | yes | export to Shopify SEO fields / Next metadata |
| Yoast SEO: WooCommerce | 16.8 | 923 product meta keys (sum) (SEO metadata) | yes | export to Shopify SEO fields / Next metadata |

## Payment, refund, fulfilment and tracking data locations

- Payment methods used across 896 orders: Credit / Debit Card ×437, Credit Card (Stripe) ×214, (none) ×132, Other ×37, Ezidebit credit/debit card. ×32, Apple Pay (Stripe) ×15, Wallet Payment ×14, Link ×11, Cash (cashier) ×2, Google Pay (Stripe) ×2
- Refund objects: 110 across 102 orders (Woo core `shop_order_refund`; Stripe refund IDs in `_stripe_refund_id` ×21)
- RMA plugin (wps_*) meta present on 217 orders
- Order/line meta keys that look like carrier/tracking data: _googlesitekit_ga_purchase_event_tracked
- Non-core database tables reported by WooCommerce system status: 133 (see `exports/system_status.json`)
- Invoices/packing slips: no invoice plugin active; WooCommerce order emails are the only customer-facing documents.

## Sitemap / SEO

- Yoast sitemap URLs: 292 across 11 sub-sitemaps
- Yoast Premium redirect manager is not exposed via REST: export `SEO → Redirects → Export` (CSV) manually and add to `url-inventory.csv`.
