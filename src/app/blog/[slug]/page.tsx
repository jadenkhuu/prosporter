import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

import { blogSlugs } from "../slugs";

/**
 * PLACEHOLDER ROUTE (CLNT-175). This is not the real blog post page.
 *
 * 14 legacy post URLs 308 to `/blog/<slug>`; this keeps those redirects landing on
 * a 200 instead of a 404 until the CMS work lands. The route is limited to exactly
 * the slugs in the redirect map, so an unknown `/blog/anything` still 404s rather
 * than becoming a soft 404. `dynamicParams = false` alone is not enough for that:
 * the root layout reads the cart cookie, which makes every route render
 * dynamically, so the explicit `notFound()` below is what enforces the list.
 * Replace wholesale; nothing here is meant to survive.
 */
export const dynamicParams = false;

export function generateStaticParams() {
  return blogSlugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  if (!blogSlugs.includes(slug)) return { title: "Not found · ProSporter" };
  return {
    title: `${slug.replace(/-/g, " ")} · ProSporter`,
    robots: { index: false, follow: true },
  };
}

export default async function BlogPostPlaceholder({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  if (!blogSlugs.includes(slug)) notFound();
  return (
    <div className="mx-auto max-w-[720px] px-4 py-24 sm:px-6 lg:px-8">
      <p className="eyebrow text-subtle">Journal</p>
      <h1 className="display mt-3 text-3xl sm:text-4xl">
        {slug.replace(/-/g, " ")}
      </h1>
      <p className="mt-4 text-sm text-muted">
        This article is being migrated from the old site. Its address will not
        change, so this link stays good.
      </p>
      <div className="mt-10 flex flex-wrap gap-3">
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
    </div>
  );
}
