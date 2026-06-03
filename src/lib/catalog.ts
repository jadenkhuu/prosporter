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
  "protective-gear",
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

export type Scope = {
  title: string;
  kind: "all" | "category" | "surface" | "club" | "new" | "sale";
  description?: string;
  products: Product[];
};

/**
 * Resolve a catch-all `/shop/...` path into a scoped product set.
 * Handles: [], [category], [surface], [sale|new-arrivals], [clubs, slug].
 * Returns null for an unknown path so the route can 404.
 */
export function resolveScope(segments: string[]): Scope | null {
  if (segments.length === 0) {
    return { title: "Shop All", kind: "all", products: catalog };
  }

  const [first, second] = segments;

  if (first === "clubs" && second) {
    const club = taxonomy.collections.find((c) => c.id === second && c.type === "club");
    if (!club) return null;
    return {
      title: club.label,
      kind: "club",
      description: `Official ${club.label} teamwear.`,
      products: catalog.filter((p) => p.clubs.includes(second)),
    };
  }

  if (segments.length > 1) return null;

  const category = taxonomy.primary_nav.find((c) => c.id === first);
  if (category) {
    return {
      title: category.label,
      kind: "category",
      products: catalog.filter((p) => p.primary_category === first),
    };
  }

  if (first === "beach" || first === "indoor") {
    return {
      title: first === "beach" ? "Beach" : "Indoor",
      kind: "surface",
      description:
        first === "beach"
          ? "Built for sand, sun and the beach game."
          : "Court-ready gear for the indoor season.",
      products: catalog.filter((p) => p.surface === first),
    };
  }

  if (first === "new-arrivals") {
    return {
      title: "New Arrivals",
      kind: "new",
      description: "The latest drops across the range.",
      products: byNewest(catalog).slice(0, 24),
    };
  }

  if (first === "sale") {
    return {
      title: "Sale",
      kind: "sale",
      description: "Marked-down gear while stock lasts.",
      products: catalog.filter((p) => p.on_sale),
    };
  }

  return null;
}

/** Build facet options from a specific product set so counts reflect the current scope. */
export function buildFacets(products: Product[]) {
  const tally = (vals: string[]) => {
    const m = new Map<string, number>();
    for (const v of vals) m.set(v, (m.get(v) ?? 0) + 1);
    return m;
  };

  const genders = tally(products.flatMap((p) => p.gender));
  const surfaces = tally(products.flatMap((p) => (p.surface ? [p.surface] : [])));
  const colours = tally(products.flatMap((p) => p.colours));
  const sizes = tally(products.flatMap((p) => p.sizes));

  const SIZE_ORDER = ["4XS", "3XS", "2XS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "S/M", "M/L"];
  const orderedSizes = [...sizes.keys()].sort(
    (a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b),
  );

  const prices = products.map((p) => p.price);

  return {
    gender: [...genders.entries()].map(([value, count]) => ({ value, count })),
    surface: [...surfaces.entries()].map(([value, count]) => ({ value, count })),
    colour: [...colours.entries()]
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count),
    size: orderedSizes.map((value) => ({ value, count: sizes.get(value)! })),
    priceMin: prices.length ? Math.floor(Math.min(...prices)) : 0,
    priceMax: prices.length ? Math.ceil(Math.max(...prices)) : 0,
  };
}

export type Facets = ReturnType<typeof buildFacets>;
