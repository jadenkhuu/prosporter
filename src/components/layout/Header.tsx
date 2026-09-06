import Link from "next/link";
import Image from "next/image";
import { taxonomy } from "@/lib/catalog";
import { CartButton } from "@/components/cart/CartButton";
import { SearchDialog } from "@/components/search/SearchDialog";
import { HeaderScrollShadow } from "./HeaderScrollShadow";
import { MobileMenuButton } from "./MobileMenuButton";
import { MobileMenuPanel } from "./MobileMenuPanel";

const collectionLinks = [
  { label: "New Arrivals", href: "/shop/new-arrivals" },
  { label: "Beach", href: "/shop/beach" },
  { label: "Indoor", href: "/shop/indoor" },
];

const clubLinks = taxonomy.collections
  .filter((c) => c.type === "club")
  .map((c) => ({ label: c.label, href: `/shop/clubs/${c.id}` }));

/**
 * Server component. The header is above the fold on every route and its markup
 * is pure — logo, links, taxonomy — so none of it belongs in the client bundle.
 * When the whole header was `"use client"` it dragged `@/lib/catalog` (and with
 * it `mock-data/catalog.json`, 58 KB) plus the entire off-canvas menu into the
 * JavaScript every page had to parse before the LCP paint; Lighthouse mobile
 * attributed 65-75% of LCP to render delay because of it (QA defect D3).
 *
 * What is left on the client is three small islands: the hamburger, the search
 * dialog, and the bag button (which needs the live cart count). The menu panel
 * is a client shell around server-rendered nav markup, and the scroll shadow is
 * a headless island that toggles an attribute on `<html>`.
 */
export function Header() {
  return (
    <>
      {/* The announcement bar lives in the root layout (AnnouncementBar.tsx):
          it is static server-rendered text and paints before anything else. */}
      <header
        data-site-header
        className="sticky top-0 z-50 border-b border-line bg-paper/95 backdrop-blur transition-shadow"
      >
        <div className="mx-auto flex max-w-[1400px] items-center gap-4 px-4 py-4 sm:px-6 lg:px-8">
          {/* Mobile menu trigger */}
          <MobileMenuButton />

          {/* Brand */}
          <Link href="/" className="mr-2 flex items-center lg:mr-6" aria-label="ProSporter home">
            <Image
              src="/brand/prosporter-logo.png"
              alt="ProSporter"
              width={240}
              height={26}
              priority
              className="h-5 w-auto sm:h-6"
            />
          </Link>

          {/* Primary nav */}
          <nav aria-label="Primary" className="hidden flex-1 items-center gap-5 lg:flex">
            {taxonomy.primary_nav.map((cat) => (
              <Link
                key={cat.id}
                href={`/shop/${cat.id}`}
                className="text-sm font-medium text-ink/80 transition-colors hover:text-green-deep"
              >
                {cat.label}
              </Link>
            ))}
            <span className="h-4 w-px bg-line" />
            {collectionLinks.map((c) => (
              <Link
                key={c.href}
                href={c.href}
                className="text-sm font-medium text-ink/80 transition-colors hover:text-green-deep"
              >
                {c.label}
              </Link>
            ))}
          </nav>

          {/* Actions */}
          <div className="ml-auto flex items-center gap-1">
            <SearchDialog />
            <CartButton />
          </div>
        </div>
      </header>

      {/* Mobile menu — a body-level sibling of the header, main and footer so
          the dialog can inert all three while it is open. `inert` when closed,
          so the off-canvas links are never tab stops. The lists below are
          server markup; MobileMenuPanel only supplies the dialog behaviour. */}
      <MobileMenuPanel>
        <nav aria-label="Mobile" className="flex-1 overflow-y-auto px-5 py-4">
          <p className="eyebrow mb-2 text-subtle">Shop</p>
          <ul className="mb-6 space-y-1">
            {taxonomy.primary_nav.map((cat) => (
              <li key={cat.id}>
                <Link
                  href={`/shop/${cat.id}`}
                  className="flex items-center justify-between py-2 text-lg font-medium"
                >
                  {cat.label}
                  <span className="text-sm text-subtle tabular-nums">{cat.count}</span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="eyebrow mb-2 text-subtle">Collections</p>
          <ul className="mb-6 space-y-1">
            {collectionLinks.map((c) => (
              <li key={c.href}>
                <Link href={c.href} className="block py-2 text-lg font-medium">
                  {c.label}
                </Link>
              </li>
            ))}
          </ul>
          <p className="eyebrow mb-2 text-subtle">Clubs &amp; Teams</p>
          <ul className="space-y-1">
            {clubLinks.map((c) => (
              <li key={c.href}>
                <Link href={c.href} className="block py-2 text-lg font-medium">
                  {c.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </MobileMenuPanel>

      <HeaderScrollShadow />
    </>
  );
}
