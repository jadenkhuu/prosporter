/**
 * Neutral tile for the ~40 products that have no photo in the source yet
 * (mid-migration drafts).
 *
 * Its own module so a client component can reach it without importing the
 * server-rendered `ProductCard`.
 */
export const PLACEHOLDER_IMAGE = "/products/placeholder.svg";
