import catalogJson from "../../mock-data/catalog.json";
import taxonomyJson from "../../mock-data/taxonomy.json";

export type Product = {
  id: number;
  name: string;
  slug: string;
  type: string;
  price: number;
  currency: string;
  on_sale: boolean;
  in_stock: boolean;
  image_local: string;
  primary_category: string;
  surface: string | null;
  clubs: string[];
  gender: string[];
  colours: string[];
  sizes: string[];
  numeric_sizes: string[];
  original_categories: string[];
  /** Extra classification tags kept for future filtering (e.g. "protective-gear"). */
  tags?: string[];
};

type FacetValue = { value: string; count: number };
type Facet =
  | { id: string; label: string; type: "checkbox" | "swatch"; values: FacetValue[] }
  | { id: string; label: string; type: "range"; min: number; max: number };

export type Taxonomy = {
  primary_nav: { id: string; slug: string; label: string; count: number }[];
  collections: {
    id: string;
    slug: string;
    label: string;
    type: "surface" | "club" | "dynamic";
    count: number | null;
  }[];
  filters: Facet[];
  sort_options: string[];
};

export const catalog = catalogJson as Product[];
export const taxonomy = taxonomyJson as Taxonomy;

// Display order for primary categories (Tops & Shorts lead). Applied once at
// module load so the nav, footer, mobile menu and homepage all stay in sync.
const NAV_ORDER = [
  "tops",
  "shorts-pants",
  "hoodies-jackets",
  "jerseys",
  "accessories",
];
taxonomy.primary_nav.sort(
  (a, b) => NAV_ORDER.indexOf(a.id) - NAV_ORDER.indexOf(b.id),
);

export function getAllProducts(): Product[] {
  return catalog;
}

export function getProductBySlug(slug: string): Product | undefined {
  return catalog.find((p) => p.slug === slug);
}

/**
 * "Most popular" line — a general apparel spread (jackets, hoodies, shirts,
 * pants) for the homepage carousel. Missing slugs are skipped gracefully.
 */
const POPULAR_SLUGS = [
  "provolley-brione-full-zip-track-jacket",
  "baldo-hoodie",
  "provolley-men-training-t-shirt-navy",
  "nine-rain-jacket-nine",
  "provolley-premium-t-shirt-cinque-men",
  "provolley-winter-hoodie-2024",
  "presser-polo-t-shirt",
  "provolley-brione-track-pants",
];

export function getPopularProducts(): Product[] {
  return POPULAR_SLUGS.map((slug) => getProductBySlug(slug)).filter(
    (p): p is Product => Boolean(p),
  );
}

export function getCategoryLabel(id: string): string {
  return taxonomy.primary_nav.find((c) => c.id === id)?.label ?? id;
}

/** Products newest-first — id is a Woo post id, so higher ≈ newer for the mock. */
export function byNewest(products: Product[]): Product[] {
  return [...products].sort((a, b) => b.id - a.id);
}

/*
 * Scope resolution and facet building for both catalog sources now live in
 * `catalog-view.ts` (pure helpers) and `catalog-source.ts` (the selection
 * layer). This module stays the mock data + taxonomy primitives.
 */
