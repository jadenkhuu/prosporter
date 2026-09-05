import Link from "next/link";
import type { Metadata } from "next";

import { blogSlugs } from "./slugs";

/**
 * PLACEHOLDER ROUTE (CLNT-175). This is not the real blog.
 *
 * 17 legacy redirects (every `/category/<slug>/` and `/tag/<slug>/` archive) plus
 * the preserved legacy path `/blog` point here, so without this route the redirect
 * layer would land crawlers on a 404. It renders a "coming soon" 200 and lists
 * only the slugs the redirect map actually references. Replace it wholesale when
 * the CMS/blog work lands; nothing here is meant to survive.
 */
export const metadata: Metadata = {
  title: "Journal · ProSporter",
  robots: { index: false, follow: true },
};

export default function BlogIndexPlaceholder() {
  return (
    <div className="mx-auto max-w-[900px] px-4 py-24 sm:px-6 lg:px-8">
      <p className="eyebrow text-subtle">Journal</p>
      <h1 className="display mt-3 text-4xl sm:text-5xl">Coming soon</h1>
      <p className="mt-4 max-w-md text-sm text-muted">
        The ProSporter journal is being rebuilt. Every article from the old site
        keeps its address, so old links will keep working.
      </p>
      <ul className="mt-10 space-y-2 text-sm">
        {blogSlugs.map((slug) => (
          <li key={slug}>
            <Link href={`/blog/${slug}`} className="underline underline-offset-4">
              {slug.replace(/-/g, " ")}
            </Link>
          </li>
        ))}
      </ul>
      <div className="mt-10">
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
