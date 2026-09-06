import Link from "next/link";
import type { Metadata } from "next";

import { formatArticleDate, getArticleList } from "@/lib/content-source";
import { OG_DEFAULTS } from "@/lib/seo/metadata";

/**
 * Blog index (CLNT-171). Every legacy `/category/<slug>/` and `/tag/<slug>/`
 * archive plus the preserved `/blog` path lands here, so the route must always
 * answer 200 — including when Shopify is unconfigured, where the list is empty.
 *
 * Articles come from the `news` blog, newest first; `-2` duplicate handles left
 * by the WooCommerce export are filtered out of the listing in `content.ts`.
 */
const BLOG_DESCRIPTION = "News, guides and product notes from the ProSporter team.";

export const metadata: Metadata = {
  title: "Journal · ProSporter",
  description: BLOG_DESCRIPTION,
  alternates: { canonical: "/blog" },
  openGraph: {
    ...OG_DEFAULTS,
    type: "website",
    url: "/blog",
    title: "Journal · ProSporter",
    description: BLOG_DESCRIPTION,
  },
};

export default async function BlogIndex() {
  const articles = await getArticleList();

  return (
    <div className="mx-auto max-w-[1000px] px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
      <p className="eyebrow text-subtle">Journal</p>
      <h1 className="display mt-3 text-4xl sm:text-5xl">Latest articles</h1>

      {articles.length === 0 ? (
        <p className="mt-8 max-w-md text-sm text-muted">
          There are no articles to show right now. Please check back soon.
        </p>
      ) : (
        <ul className="mt-12 grid gap-10 sm:grid-cols-2">
          {articles.map((article) => {
            const date = formatArticleDate(article.publishedAt);
            return (
              <li key={article.handle}>
                <Link href={`/blog/${article.handle}`} className="group block">
                  {article.image && (
                    // Migrated article images are served by Shopify's CDN; a plain
                    // <img> keeps the route free of intrinsic-size guesswork for
                    // assets whose dimensions the listing query does not rely on.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={article.image.url}
                      alt={article.image.alt ?? ""}
                      className="mb-4 aspect-[3/2] w-full rounded-lg object-cover"
                    />
                  )}
                  {date && (
                    <time dateTime={article.publishedAt ?? undefined} className="eyebrow text-subtle">
                      {date}
                    </time>
                  )}
                  <h2 className="mt-2 text-lg font-semibold transition-colors group-hover:text-ink-2">
                    {article.title}
                  </h2>
                  {article.excerpt && (
                    <p className="mt-2 line-clamp-3 text-sm text-muted">{article.excerpt}</p>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-16">
        <Link
          href="/shop"
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
        >
          Shop all
        </Link>
      </div>
    </div>
  );
}
