import Link from "next/link";
import Image from "next/image";
import { taxonomy } from "@/lib/catalog";

const cols = [
  {
    title: "Shop",
    links: taxonomy.primary_nav.map((c) => ({
      label: c.label,
      href: `/shop/${c.id}`,
    })),
  },
  {
    title: "Collections",
    links: [
      { label: "New Arrivals", href: "/shop/new-arrivals" },
      { label: "Beach", href: "/shop/beach" },
      { label: "Indoor", href: "/shop/indoor" },
      { label: "Sale", href: "/shop/sale" },
    ],
  },
  {
    title: "Clubs & Teams",
    links: taxonomy.collections
      .filter((c) => c.type === "club")
      .map((c) => ({ label: c.label, href: `/shop/clubs/${c.id}` })),
  },
];

export function Footer() {
  return (
    <footer className="mt-20 border-t border-line bg-surface">
      <div className="mx-auto max-w-[1400px] px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div>
            <Link href="/" className="inline-flex items-center" aria-label="ProSporter home">
              <Image
                src="/brand/prosporter-logo.png"
                alt="ProSporter"
                width={240}
                height={26}
                className="h-7 w-auto"
              />
            </Link>
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-muted">
              Indoor and beach volleyball apparel, club teamwear and protective
              gear. Built for the Australian game.
            </p>
          </div>
          {cols.map((col) => (
            <div key={col.title}>
              <h3 className="eyebrow mb-3 text-subtle">{col.title}</h3>
              <ul className="space-y-2">
                {col.links.map((l) => (
                  <li key={l.href}>
                    <Link
                      href={l.href}
                      className="text-sm text-muted transition-colors hover:text-ink"
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-line pt-6 text-xs text-subtle sm:flex-row sm:items-center">
          <p>© {new Date().getFullYear()} ProSporter. All rights reserved.</p>
          <p>
            Headless storefront · checkout secured on{" "}
            <span className="text-muted">prosporter.com.au</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
