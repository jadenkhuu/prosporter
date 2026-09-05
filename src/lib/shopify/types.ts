/** Storefront API shapes returned by the fragments in ./fragments.ts. */
export type Money = { amount: string; currencyCode: string };

export type Image = {
  id: string | null;
  url: string;
  altText: string | null;
  width: number | null;
  height: number | null;
};

export type SelectedOption = { name: string; value: string };

export type ProductOption = {
  id: string;
  name: string;
  optionValues: { id: string; name: string; swatch: { color: string | null } | null }[];
};

export type ProductVariant = {
  id: string;
  title: string;
  sku: string | null;
  barcode: string | null;
  availableForSale: boolean;
  currentlyNotInStock: boolean;
  quantityAvailable: number | null;
  price: Money;
  compareAtPrice: Money | null;
  selectedOptions: SelectedOption[];
  image: Image | null;
  weight: number | null;
  weightUnit: "KILOGRAMS" | "GRAMS" | "POUNDS" | "OUNCES";
  requiresShipping: boolean;
};

export type Seo = { title: string | null; description: string | null };

export type Metafield = { namespace: string; key: string; type: string; value: string } | null;

export type PageInfo = {
  hasNextPage: boolean;
  hasPreviousPage: boolean;
  startCursor: string | null;
  endCursor: string | null;
};

export type Connection<T> = { edges: { cursor: string; node: T }[]; pageInfo: PageInfo };

export type Collection = {
  id: string;
  handle: string;
  title: string;
  description: string;
  descriptionHtml: string;
  updatedAt: string;
  seo: Seo;
  image: Image | null;
};

/** Lighter shape for listing grids; avoids fetching every variant per card. */
export type ProductCard = {
  id: string;
  handle: string;
  title: string;
  vendor: string;
  productType: string;
  tags: string[];
  createdAt: string;
  availableForSale: boolean;
  featuredImage: Image | null;
  priceRange: { minVariantPrice: Money; maxVariantPrice: Money };
  compareAtPriceRange: { minVariantPrice: Money; maxVariantPrice: Money };
  /** First two variants only: enough to tell a single-variant product apart. */
  quickAddVariants: { edges: { node: { id: string; availableForSale: boolean } }[] };
  options: ProductOption[];
};

export type Product = ProductCard & {
  description: string;
  descriptionHtml: string;
  totalInventory: number | null;
  updatedAt: string;
  seo: Seo;
  images: Connection<Image>;
  variants: Connection<ProductVariant>;
  collections: Connection<Pick<Collection, "id" | "handle" | "title">>;
  metafields: Metafield[];
};

export type CartLine = {
  id: string;
  quantity: number;
  attributes: { key: string; value: string }[];
  cost: { totalAmount: Money; amountPerQuantity: Money; compareAtAmountPerQuantity: Money | null };
  merchandise: {
    id: string;
    title: string;
    sku: string | null;
    availableForSale: boolean;
    quantityAvailable: number | null;
    selectedOptions: SelectedOption[];
    image: Image | null;
    price: Money;
    compareAtPrice: Money | null;
    product: { id: string; handle: string; title: string; featuredImage: Image | null };
  };
};

export type Cart = {
  id: string;
  checkoutUrl: string;
  createdAt: string;
  updatedAt: string;
  totalQuantity: number;
  note: string | null;
  buyerIdentity: { email: string | null; countryCode: string | null };
  discountCodes: { code: string; applicable: boolean }[];
  cost: {
    subtotalAmount: Money;
    totalAmount: Money;
    totalTaxAmount: Money | null;
    totalDutyAmount: Money | null;
  };
  lines: Connection<CartLine>;
};

export type UserError = { field: string[] | null; message: string; code?: string };

/** Flatten a Storefront connection to its nodes. */
export function nodes<T>(c: Connection<T> | null | undefined): T[] {
  return c?.edges.map((e) => e.node) ?? [];
}
