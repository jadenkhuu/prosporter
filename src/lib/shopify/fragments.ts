/**
 * Storefront GraphQL fragments. Keep field lists in sync with ./types.ts.
 *
 * Metafields: every product read requests the same fixed identifier list so the
 * storefront can rely on them without per-call variation. Add to
 * PRODUCT_METAFIELD_IDENTIFIERS when the approved mapping defines a new field.
 */
export const PRODUCT_METAFIELD_IDENTIFIERS = [
  { namespace: "prosporter", key: "surface" },
  { namespace: "prosporter", key: "club" },
  { namespace: "prosporter", key: "gender" },
  { namespace: "prosporter", key: "size_guide" },
  { namespace: "prosporter", key: "personalisation" },
];

export const MONEY_FRAGMENT = /* GraphQL */ `
  fragment Money on MoneyV2 {
    amount
    currencyCode
  }
`;

export const IMAGE_FRAGMENT = /* GraphQL */ `
  fragment Image on Image {
    id
    url
    altText
    width
    height
  }
`;

export const SEO_FRAGMENT = /* GraphQL */ `
  fragment Seo on SEO {
    title
    description
  }
`;

export const VARIANT_FRAGMENT = /* GraphQL */ `
  fragment Variant on ProductVariant {
    id
    title
    sku
    barcode
    availableForSale
    currentlyNotInStock
    quantityAvailable
    price { ...Money }
    compareAtPrice { ...Money }
    selectedOptions { name value }
    image { ...Image }
    weight
    weightUnit
    requiresShipping
  }
`;

export const PRODUCT_OPTIONS_FRAGMENT = /* GraphQL */ `
  fragment ProductOptions on Product {
    options {
      id
      name
      optionValues {
        id
        name
        swatch { color }
      }
    }
  }
`;

/** Grid/listing shape. */
export const PRODUCT_CARD_FRAGMENT = /* GraphQL */ `
  fragment ProductCard on Product {
    id
    handle
    title
    vendor
    productType
    tags
    availableForSale
    featuredImage { ...Image }
    priceRange {
      minVariantPrice { ...Money }
      maxVariantPrice { ...Money }
    }
    compareAtPriceRange {
      minVariantPrice { ...Money }
      maxVariantPrice { ...Money }
    }
    ...ProductOptions
  }
`;

/** Full product detail shape. Requires a $metafieldIdentifiers variable. */
export const PRODUCT_FRAGMENT = /* GraphQL */ `
  fragment Product on Product {
    ...ProductCard
    description
    descriptionHtml
    totalInventory
    createdAt
    updatedAt
    seo { ...Seo }
    images(first: 50) {
      edges { cursor node { ...Image } }
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    }
    variants(first: 250) {
      edges { cursor node { ...Variant } }
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    }
    collections(first: 20) {
      edges { cursor node { id handle title } }
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    }
    metafields(identifiers: $metafieldIdentifiers) {
      namespace
      key
      type
      value
    }
  }
`;

export const COLLECTION_FRAGMENT = /* GraphQL */ `
  fragment Collection on Collection {
    id
    handle
    title
    description
    descriptionHtml
    updatedAt
    seo { ...Seo }
    image { ...Image }
  }
`;

export const CART_FRAGMENT = /* GraphQL */ `
  fragment Cart on Cart {
    id
    checkoutUrl
    createdAt
    updatedAt
    totalQuantity
    note
    buyerIdentity { email countryCode }
    discountCodes { code applicable }
    cost {
      subtotalAmount { ...Money }
      totalAmount { ...Money }
      totalTaxAmount { ...Money }
      totalDutyAmount { ...Money }
    }
    lines(first: 250) {
      edges {
        cursor
        node {
          id
          quantity
          attributes { key value }
          cost {
            totalAmount { ...Money }
            amountPerQuantity { ...Money }
            compareAtAmountPerQuantity { ...Money }
          }
          merchandise {
            ... on ProductVariant {
              id
              title
              sku
              availableForSale
              quantityAvailable
              selectedOptions { name value }
              image { ...Image }
              price { ...Money }
              compareAtPrice { ...Money }
              product { id handle title featuredImage { ...Image } }
            }
          }
        }
      }
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
    }
  }
`;

/** Everything a full product query needs, in dependency order. */
export const PRODUCT_FRAGMENTS = [
  MONEY_FRAGMENT,
  IMAGE_FRAGMENT,
  SEO_FRAGMENT,
  VARIANT_FRAGMENT,
  PRODUCT_OPTIONS_FRAGMENT,
  PRODUCT_CARD_FRAGMENT,
  PRODUCT_FRAGMENT,
].join("\n");

export const PRODUCT_CARD_FRAGMENTS = [
  MONEY_FRAGMENT,
  IMAGE_FRAGMENT,
  PRODUCT_OPTIONS_FRAGMENT,
  PRODUCT_CARD_FRAGMENT,
].join("\n");

export const COLLECTION_FRAGMENTS = [IMAGE_FRAGMENT, SEO_FRAGMENT, COLLECTION_FRAGMENT].join("\n");

/** Collection page needs both; Image/Money are shared so include each once. */
export const COLLECTION_PAGE_FRAGMENTS = [
  MONEY_FRAGMENT,
  IMAGE_FRAGMENT,
  SEO_FRAGMENT,
  COLLECTION_FRAGMENT,
  PRODUCT_OPTIONS_FRAGMENT,
  PRODUCT_CARD_FRAGMENT,
].join("\n");

export const CART_FRAGMENTS = [MONEY_FRAGMENT, IMAGE_FRAGMENT, CART_FRAGMENT].join("\n");
