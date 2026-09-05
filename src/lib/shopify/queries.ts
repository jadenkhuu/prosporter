import {
  CART_FRAGMENTS,
  COLLECTION_FRAGMENTS,
  COLLECTION_PAGE_FRAGMENTS,
  PRODUCT_CARD_FRAGMENTS,
  PRODUCT_FRAGMENTS,
} from "./fragments";

const PAGE_INFO = "pageInfo { hasNextPage hasPreviousPage startCursor endCursor }";

export const GET_PRODUCT_BY_HANDLE = /* GraphQL */ `
  ${PRODUCT_FRAGMENTS}
  query GetProductByHandle($handle: String!, $metafieldIdentifiers: [HasMetafieldsIdentifier!]!) {
    product(handle: $handle) { ...Product }
  }
`;

export const GET_PRODUCTS = /* GraphQL */ `
  ${PRODUCT_CARD_FRAGMENTS}
  query GetProducts($first: Int!, $after: String, $query: String, $sortKey: ProductSortKeys, $reverse: Boolean) {
    products(first: $first, after: $after, query: $query, sortKey: $sortKey, reverse: $reverse) {
      edges { cursor node { ...ProductCard } }
      ${PAGE_INFO}
    }
  }
`;

export const GET_PRODUCT_HANDLES = /* GraphQL */ `
  query GetProductHandles($first: Int!, $after: String) {
    products(first: $first, after: $after) {
      edges { cursor node { handle updatedAt } }
      ${PAGE_INFO}
    }
  }
`;

export const GET_COLLECTIONS = /* GraphQL */ `
  ${COLLECTION_FRAGMENTS}
  query GetCollections($first: Int!, $after: String) {
    collections(first: $first, after: $after) {
      edges { cursor node { ...Collection } }
      ${PAGE_INFO}
    }
  }
`;

export const GET_COLLECTION_BY_HANDLE = /* GraphQL */ `
  ${COLLECTION_PAGE_FRAGMENTS}
  query GetCollectionByHandle(
    $handle: String!
    $first: Int!
    $after: String
    $sortKey: ProductCollectionSortKeys
    $reverse: Boolean
    $filters: [ProductFilter!]
  ) {
    collection(handle: $handle) {
      ...Collection
      products(first: $first, after: $after, sortKey: $sortKey, reverse: $reverse, filters: $filters) {
        edges { cursor node { ...ProductCard } }
        ${PAGE_INFO}
        filters {
          id
          label
          type
          values { id label count input }
        }
      }
    }
  }
`;

export const GET_CART = /* GraphQL */ `
  ${CART_FRAGMENTS}
  query GetCart($id: ID!) {
    cart(id: $id) { ...Cart }
  }
`;

const CART_USER_ERRORS = "userErrors { field message code }";

export const CART_CREATE = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartCreate($input: CartInput) {
    cartCreate(input: $input) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;

export const CART_LINES_ADD = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartLinesAdd($cartId: ID!, $lines: [CartLineInput!]!) {
    cartLinesAdd(cartId: $cartId, lines: $lines) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;

export const CART_LINES_UPDATE = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartLinesUpdate($cartId: ID!, $lines: [CartLineUpdateInput!]!) {
    cartLinesUpdate(cartId: $cartId, lines: $lines) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;

export const CART_LINES_REMOVE = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartLinesRemove($cartId: ID!, $lineIds: [ID!]!) {
    cartLinesRemove(cartId: $cartId, lineIds: $lineIds) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;

export const CART_BUYER_IDENTITY_UPDATE = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartBuyerIdentityUpdate($cartId: ID!, $buyerIdentity: CartBuyerIdentityInput!) {
    cartBuyerIdentityUpdate(cartId: $cartId, buyerIdentity: $buyerIdentity) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;

export const CART_DISCOUNT_CODES_UPDATE = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartDiscountCodesUpdate($cartId: ID!, $discountCodes: [String!]) {
    cartDiscountCodesUpdate(cartId: $cartId, discountCodes: $discountCodes) { cart { ...Cart } ${CART_USER_ERRORS} }
  }
`;
