import "server-only";

/**
 * Typed Storefront reads for editorial content (CLNT-171): Shopify pages and
 * blog articles. Pages and route handlers import this module (or the wrappers
 * in `src/lib/content-source.ts`); nothing outside `src/lib/shopify/` may call
 * `shopifyFetch` directly.
 *
 * Queries were written against the live 2026-07 schema:
 *   QueryRoot.page(handle:)      -> Page
 *   QueryRoot.pages(first:...)   -> PageConnection
 *   QueryRoot.blog(handle:)      -> Blog { articles(...), articleByHandle(handle:) }
 *   Article { title handle contentHtml excerpt publishedAt authorV2 image seo tags }
 *
 * `Article.author` does not exist in 2026-07 — only `authorV2` (ArticleAuthor).
 * Reads use `force-cache` with the tags in `tags.ts` and CATALOG_REVALIDATE_SECONDS.
 */
import { shopifyFetch } from "./client";
import { CACHE_TAGS, CATALOG_REVALIDATE_SECONDS } from "./tags";
import type { ArticleCard, ContentArticle, ContentPage } from "./content-types";
import type { Connection } from "./types";

/** Storefront API hard limit on `first`. */
const PAGE_SIZE = 250;

/** Default (and only) blog created by the migration. */
export const DEFAULT_BLOG_HANDLE = "news";

const PAGE_INFO = "pageInfo { hasNextPage hasPreviousPage startCursor endCursor }";

const PAGE_FIELDS = /* GraphQL */ `
  fragment ContentPage on Page {
    id
    handle
    title
    body
    bodySummary
    createdAt
    updatedAt
    seo {
      title
      description
    }
  }
`;

// `authorV2 { name }` only: ArticleAuthor also exposes `email`, which is
// personal data and must not be fetched or rendered.
const ARTICLE_CARD_FIELDS = /* GraphQL */ `
  fragment ArticleCard on Article {
    id
    handle
    title
    excerpt
    publishedAt
    tags
    authorV2 {
      name
    }
    image {
      id
      url
      altText
      width
      height
    }
  }
`;

const GET_PAGE_BY_HANDLE = /* GraphQL */ `
  ${PAGE_FIELDS}
  query GetPageByHandle($handle: String!) {
    page(handle: $handle) {
      ...ContentPage
    }
  }
`;

const GET_PAGE_HANDLES = /* GraphQL */ `
  query GetPageHandles($first: Int!, $after: String) {
    pages(first: $first, after: $after) {
      edges {
        cursor
        node {
          handle
          updatedAt
        }
      }
      ${PAGE_INFO}
    }
  }
`;

const GET_BLOG_ARTICLES = /* GraphQL */ `
  ${ARTICLE_CARD_FIELDS}
  query GetBlogArticles($blogHandle: String!, $first: Int!) {
    blog(handle: $blogHandle) {
      handle
      title
      articles(first: $first, sortKey: PUBLISHED_AT, reverse: true) {
        edges {
          cursor
          node {
            ...ArticleCard
          }
        }
        ${PAGE_INFO}
      }
    }
  }
`;

const GET_ARTICLE_BY_HANDLE = /* GraphQL */ `
  ${ARTICLE_CARD_FIELDS}
  query GetArticleByHandle($blogHandle: String!, $handle: String!) {
    blog(handle: $blogHandle) {
      articleByHandle(handle: $handle) {
        ...ArticleCard
        contentHtml
        seo {
          title
          description
        }
      }
    }
  }
`;

const GET_ARTICLE_HANDLES = /* GraphQL */ `
  query GetArticleHandles($blogHandle: String!, $first: Int!, $after: String) {
    blog(handle: $blogHandle) {
      articles(first: $first, after: $after, sortKey: PUBLISHED_AT, reverse: true) {
        edges {
          cursor
          node {
            handle
            publishedAt
          }
        }
        ${PAGE_INFO}
      }
    }
  }
`;

/**
 * The WooCommerce export contained duplicate posts and pages whose slugs got a
 * `-2` suffix (`about-2`, `blog-2`). The migration loaded the ones that had a
 * title, so they exist in Shopify. They are hidden from listings and from
 * prerendering, but still resolve when requested directly.
 */
export function isDuplicateHandle(handle: string): boolean {
  return /-2$/.test(handle);
}

// ------------------------------------------------------------------- pages

export async function getPage(handle: string): Promise<ContentPage | null> {
  const data = await shopifyFetch<{ page: ContentPage | null }>({
    query: GET_PAGE_BY_HANDLE,
    variables: { handle },
    tags: [CACHE_TAGS.pages, CACHE_TAGS.page(handle)],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  return data.page;
}

/** Every page handle in the store, duplicates included. Walks all pages. */
export async function getAllPageHandles(): Promise<{ handle: string; updatedAt: string }[]> {
  type Node = { handle: string; updatedAt: string };
  const all: Node[] = [];
  let after: string | null = null;
  do {
    const data: { pages: Connection<Node> } = await shopifyFetch({
      query: GET_PAGE_HANDLES,
      variables: { first: PAGE_SIZE, after },
      tags: [CACHE_TAGS.pages],
      revalidate: CATALOG_REVALIDATE_SECONDS,
    });
    all.push(...data.pages.edges.map((e) => e.node));
    after = data.pages.pageInfo.hasNextPage ? data.pages.pageInfo.endCursor : null;
  } while (after);
  return all;
}

// ---------------------------------------------------------------- articles

/** Newest first. Duplicate (`-2`) handles are filtered out of the listing. */
export async function getBlogArticles(
  blogHandle: string = DEFAULT_BLOG_HANDLE,
  first = 50,
): Promise<ArticleCard[]> {
  const data = await shopifyFetch<{
    blog: { handle: string; title: string; articles: Connection<ArticleCard> } | null;
  }>({
    query: GET_BLOG_ARTICLES,
    variables: { blogHandle, first: Math.min(first, PAGE_SIZE) },
    tags: [CACHE_TAGS.articles],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  if (!data.blog) return [];
  return data.blog.articles.edges.map((e) => e.node).filter((a) => !isDuplicateHandle(a.handle));
}

export async function getArticle(
  blogHandle: string,
  handle: string,
): Promise<ContentArticle | null> {
  const data = await shopifyFetch<{ blog: { articleByHandle: ContentArticle | null } | null }>({
    query: GET_ARTICLE_BY_HANDLE,
    variables: { blogHandle, handle },
    tags: [CACHE_TAGS.articles, CACHE_TAGS.article(handle)],
    revalidate: CATALOG_REVALIDATE_SECONDS,
  });
  return data.blog?.articleByHandle ?? null;
}

/** Every article handle in the blog, duplicates included. Walks all pages. */
export async function getAllArticleHandles(
  blogHandle: string = DEFAULT_BLOG_HANDLE,
): Promise<{ handle: string; publishedAt: string }[]> {
  type Node = { handle: string; publishedAt: string };
  const all: Node[] = [];
  let after: string | null = null;
  do {
    const data: { blog: { articles: Connection<Node> } | null } = await shopifyFetch({
      query: GET_ARTICLE_HANDLES,
      variables: { blogHandle, first: PAGE_SIZE, after },
      tags: [CACHE_TAGS.articles],
      revalidate: CATALOG_REVALIDATE_SECONDS,
    });
    if (!data.blog) return all;
    all.push(...data.blog.articles.edges.map((e) => e.node));
    after = data.blog.articles.pageInfo.hasNextPage ? data.blog.articles.pageInfo.endCursor : null;
  } while (after);
  return all;
}

export type { ArticleCard, ArticleAuthor, ContentArticle, ContentPage } from "./content-types";
