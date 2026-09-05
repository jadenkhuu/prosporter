/**
 * Storefront shapes for editorial content: Shopify pages and blog articles.
 *
 * Kept separate from `types.ts` (products, collections, carts) so the content
 * slice can evolve without touching the catalog data layer. Field names and
 * nullability were verified against the live 2026-07 Storefront schema
 * (`Page`, `Blog`, `Article`, `ArticleAuthor`).
 */
import type { Image, Seo } from "./types";

export type { Image, Seo } from "./types";

/** `Page` — `body` is the raw stored HTML (WordPress/Elementor markup after the migration). */
export type ContentPage = {
  id: string;
  handle: string;
  title: string;
  body: string;
  bodySummary: string;
  createdAt: string;
  updatedAt: string;
  seo: Seo | null;
};

/**
 * `ArticleAuthor`. Only `name` is read: the type also exposes `email`, which is
 * personal data the storefront has no reason to fetch, log or render.
 */
export type ArticleAuthor = { name: string };

/** Listing shape for `/blog`. */
export type ArticleCard = {
  id: string;
  handle: string;
  title: string;
  excerpt: string | null;
  publishedAt: string;
  image: Image | null;
  authorV2: ArticleAuthor | null;
  tags: string[];
};

/** Full article for `/blog/[slug]`. `contentHtml` is non-null in the schema. */
export type ContentArticle = ArticleCard & {
  contentHtml: string;
  seo: Seo | null;
};
