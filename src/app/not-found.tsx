import Link from "next/link";
import type { Metadata } from "next";

/**
 * The 404 route used to inherit the home page's description verbatim, which put
 * the same sentence on every dead URL (QA defect D8). It gets its own copy and
 * an explicit `noindex` — a not-found page is never a search result, and the
 * route is reachable at any path, so there is no one canonical URL to declare.
 */
export const metadata: Metadata = {
  title: "Page not found · ProSporter",
  description:
    "This ProSporter page could not be found. Browse the shop or head back to the home page.",
  robots: { index: false, follow: true },
};

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col items-center px-4 py-24 text-center sm:px-6 lg:px-8 lg:py-32">
      <p className="eyebrow text-subtle">404</p>
      <h1 className="display mt-3 text-4xl sm:text-5xl">Out of bounds</h1>
      <p className="mt-4 max-w-md text-sm text-muted">
        That page has moved or never existed. Head back to the shop or start from the home page.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/shop"
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
        >
          Shop all
        </Link>
        <Link
          href="/"
          className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-surface"
        >
          Home
        </Link>
      </div>
    </div>
  );
}
