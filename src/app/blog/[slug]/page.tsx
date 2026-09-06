import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

import { formatArticleDate, getArticleSlugs, getArticleView } from "@/lib/content-source";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd } from "@/lib/seo/json-ld";
import { OG_DEFAULTS } from "@/lib/seo/metadata";

/**
 * Blog article (CLNT-171). 14 legacy post URLs 308 to `/blog/<slug>`; the
 * migrated `news` blog keeps those handles, so the redirects land on a 200.
 *
 * `dynamicParams` stays at its default (`true`) so an article published after
 * the last deploy resolves on demand. An unknown slug is still a hard 404: the
 * explicit `notFound()` below does that work, and it is needed regardless —
 * the root layout reads the cart cookie, so every route renders dynamically and
 * `dynamicParams: false` alone would not enforce the list.
 */
export const dynamicParams = true;

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return (await getArticleSlugs()).map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticleView(slug);
  if (!article) return { title: "Not found · ProSporter" };

  const description = article.description ?? undefined;
  return {
    title: article.seoTitle || `${article.title} · ProSporter`,
    description,
    alternates: { canonical: `/blog/${article.handle}` },
    openGraph: {
      ...OG_DEFAULTS,
      type: "article",
      url: `/blog/${article.handle}`,
      title: article.seoTitle || article.title,
      description,
      publishedTime: article.publishedAt ?? undefined,
      images: article.image ? [{ url: article.image.url }] : undefined,
    },
  };
}

export default async function BlogArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = await getArticleView(slug);
  if (!article) notFound();

  const date = formatArticleDate(article.publishedAt);

  /**
   * Article structured data. The byline carries the author's display name only,
   * exactly as it is rendered below — `authorV2.email` is never fetched by the
   * data layer and must never appear here. Shopify's Storefront API exposes no
   * article `updatedAt`, so `dateModified` falls back to `publishedAt`.
   */
  const articleJsonLd = buildArticleJsonLd({
    path: `/blog/${article.handle}`,
    headline: article.title,
    description: article.description,
    image: article.image?.url,
    datePublished: article.publishedAt,
    authorName: article.author,
  });

  const breadcrumbJsonLd = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Journal", path: "/blog" },
    { name: article.title, path: `/blog/${article.handle}` },
  ]);

  return (
    <article className="mx-auto max-w-[760px] px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
      <JsonLd data={[articleJsonLd, breadcrumbJsonLd]} />
      <Link href="/blog" className="eyebrow text-subtle transition-colors hover:text-ink">
        ← Journal
      </Link>
      <h1 className="display mt-4 text-3xl sm:text-4xl">{article.title}</h1>

      <p className="mt-4 text-xs text-subtle">
        {date && <time dateTime={article.publishedAt ?? undefined}>{date}</time>}
        {date && article.author && <span aria-hidden="true"> · </span>}
        {article.author}
      </p>

      {article.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={article.image.url}
          alt={article.image.alt ?? ""}
          className="mt-8 w-full rounded-lg object-cover"
        />
      )}

      {article.unavailable ? (
        <p className="mt-8 text-sm text-muted">
          This article is not available right now. Please try again shortly.
        </p>
      ) : (
        <div
          className="page-content mt-8 text-sm leading-relaxed text-muted"
          // Sanitised in `src/lib/content-html.ts` before it reaches the DOM.
          dangerouslySetInnerHTML={{ __html: article.html }}
        />
      )}

      <div className="mt-16 flex flex-wrap gap-3">
        <Link
          href="/blog"
          className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-surface"
        >
          All articles
        </Link>
        <Link
          href="/shop"
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
        >
          Shop all
        </Link>
      </div>
    </article>
  );
}
