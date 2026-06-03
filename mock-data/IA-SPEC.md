# ProSporter — Information Architecture & Filter Spec

Proposed category structure for the headless storefront rebuild, mapped against all
94 live products. Inspired structurally by rebelsport.com.au (shop-by-type + shop-by-who)
and volleyballshop.com.au (Indoor/Beach split, protective-gear taxonomy), but kept
apparel-led because ProSporter is a single-brand teamwear label, not a multi-brand retailer.

## The principle: separate the four axes

The current WooCommerce store mixes product-type, surface, club, and gender into one flat
list of 24 categories, so nothing has a clean home. This spec splits them:

| Axis | Becomes | Why |
|------|---------|-----|
| Product type | **Primary nav** (category tree) | The stable, MECE backbone |
| Surface (Indoor/Beach) | **Collection** + filter | Volleyball-native, real beach line (32 items) |
| Club/Team | **Collection** ("Clubs & Teams") | ProSporter's differentiator |
| Gender | **Filter only** | Catalog too small for Mens/Womens top-level |

## Primary navigation (shop by type)

| Category | Slug | Products |
|----------|------|---------:|
| Shorts & Pants | `shorts-pants` | 34 |
| Tops | `tops` | 21 |
| Hoodies & Jackets | `hoodies-jackets` | 15 |
| Jerseys | `jerseys` | 7 |
| Protective Gear | `protective-gear` | 6 |
| Accessories | `accessories` | 9 |
| Coaching | `coaching` | 2 |

## Secondary nav (collections — other axes, NOT mixed into the type tree)

- **Beach** (`/beach`) — 32 products (surface)
- **Indoor** (`/indoor`) — 9 products (surface)
- **Clubs & Teams** — ProVolley Academy (19), Inner West Volley (7), Teamwear (4)
- **New Arrivals** (`/new-arrivals`) — dynamic
- **Sale** (`/sale`) — driven by `on_sale`

> Note: 53 products have no surface tag (general apparel like hoodies/tees) — intentional;
> they appear regardless of an Indoor/Beach filter.

## Filters (facets, applied on any listing page)

- **Gender** — women (24), men (3), unisex (70)
- **Surface** — beach (32), indoor (9)
- **Colour** (swatch) — Navy (30), Black (30), White (18), Yellow (6), Grey (5), Red (3), + Royal Blue, Blue, Orange, Green, Sky Blue
- **Size** — 4XS · 3XS · 2XS · XS · S · M · L · XL · 2XL · 3XL · S/M · M/L
- **Price** — range $9.90 – $219.95 AUD
- **Availability** — In stock, On sale

Sort: featured · price ↑ · price ↓ · newest · name A–Z

## Data cleanup required in WooCommerce (flag in quote)

These are *data* tasks, not frontend work — clean facets depend on them:

1. **Merge `Color` + `Colour`** into one global attribute. Also merge value synonyms:
   "Navy Blue" → Navy, "Gray"/"Light Gray" → Grey. (Done in the mapping, should be fixed at source.)
2. **Normalize Gender** values: store has `Men/Women/Male/Female` → standardize to `Men`/`Women`.
3. **Normalize sizes**: `XXL`→`2XL`, `3X`→`3XL`, `SM`→`S/M`. Keep sock sizing (e.g. `36-41`)
   as a separate attribute from apparel sizing — 4 sock products use numeric ranges.
4. **8 products have no product-type category** — currently auto-inferred from their name.
   Should be assigned a real category at source. The one true fallback ("Ace Unisex")
   needs a human decision.
5. Fold singleton legacy categories (Sweat Suit ×1, etc.) into their parent groups.

## Files

- `taxonomy.json` — the nav + filter definitions above, with live counts (feed to UI/AI).
- `catalog.json` — all 94 products mapped to `primary_category`, `surface`, `clubs[]`,
  `gender[]`, normalized `colours[]` / `sizes[]`, plus `original_categories` for traceability.
- `build_taxonomy.py` — re-runnable; regenerates both from `products.json`.
