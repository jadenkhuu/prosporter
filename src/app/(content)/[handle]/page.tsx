import { notFound } from "next/navigation";
import type { Metadata } from "next";

import { getContentPage, getContentPageHandles } from "@/lib/content-source";

/**
 * Shopify pages at the top level (CLNT-171): `/about`, `/contact`, `/faq`,
 * `/size-guide`, `/privacy-policy`, `/refund-policy`, `/terms-of-service` and
 * anything else the client publishes as a page.
 *
 * `docs/redirects/redirect-map.csv` preserves those legacy WordPress paths as
 * `same_url` 200s, so they must resolve here rather than through a redirect.
 *
 * Routing: Next.js matches static segments before dynamic ones, so `/shop`,
 * `/product/...`, `/blog`, `/search`, `/cart` and `/api/...` keep their own
 * routes; this segment only sees what is left over. Handles that collide with
 * those segments are dropped from `generateStaticParams` in `content-source.ts`
 * so the build never emits an unreachable page for them.
 *
 * `dynamicParams` is left at its default (`true`) on purpose: a page published
 * in Shopify after the last deploy then resolves on demand instead of 404ing
 * until someone rebuilds. Correct 404s do not depend on it — `getContentPage`
 * returns null for an unknown handle and this component calls `notFound()`
 * explicitly. That explicit call is required either way: the root layout reads
 * the cart cookie, so every route renders dynamically and `dynamicParams: false`
 * alone would not turn `/nonsense` into a 404.
 */
export const dynamicParams = true;

/** Legacy handles in mock mode; every published page handle otherwise. */
export async function generateStaticParams(): Promise<{ handle: string }[]> {
  return (await getContentPageHandles()).map((handle) => ({ handle }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<Metadata> {
  const { handle } = await params;
  const page = await getContentPage(handle);
  if (!page) return { title: "Not found · ProSporter" };

  const description = page.description ?? undefined;
  return {
    title: page.seoTitle || `${page.title} · ProSporter`,
    description,
    alternates: { canonical: `/${page.handle}` },
    openGraph: {
      type: "article",
      title: page.seoTitle || page.title,
      description,
    },
  };
}

export default async function ContentPageRoute({
  params,
}: {
  params: Promise<{ handle: string }>;
}) {
  const { handle } = await params;
  const page = await getContentPage(handle);
  if (!page) notFound();

  return (
    <article className="mx-auto max-w-[820px] px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
      <h1 className="display text-4xl sm:text-5xl">{page.title}</h1>
      {page.unavailable ? (
        <p className="mt-6 text-sm text-muted">
          This page is not available right now. Please try again shortly.
        </p>
      ) : (
        <div
          className="page-content mt-8 text-sm leading-relaxed text-muted"
          // Sanitised in `src/lib/content-html.ts`: WordPress block comments,
          // scripts, styles, iframes, forms and every builder attribute are
          // removed before the migrated HTML reaches the DOM.
          dangerouslySetInnerHTML={{ __html: page.html }}
        />
      )}
    </article>
  );
}
