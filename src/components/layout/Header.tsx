"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { taxonomy } from "@/lib/catalog";
import { useCart } from "@/components/cart/CartProvider";
import { CartDrawer } from "@/components/cart/CartDrawer";
import { BagIcon, MenuIcon, CloseIcon, SearchIcon } from "@/components/icons";

const collectionLinks = [
  { label: "New Arrivals", href: "/shop/new-arrivals" },
  { label: "Beach", href: "/shop/beach" },
  { label: "Indoor", href: "/shop/indoor" },
];

const clubLinks = taxonomy.collections
  .filter((c) => c.type === "club")
  .map((c) => ({ label: c.label, href: `/shop/clubs/${c.id}` }));

export function Header() {
  const { count, open } = useCart();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  return (
    <>
      {/* Announcement bar */}
      <div className="bg-ink text-paper">
        <div className="mx-auto flex max-w-[1400px] items-center justify-center px-4 py-2 text-center">
          <span className="eyebrow text-[10px] text-surface-2">
            EXAMPLE PROMOTIONAL TEXT || Free shipping on orders over $150 · Australia-wide
          </span>
        </div>
      </div>

      <header
        className={`sticky top-0 z-50 bg-paper/95 backdrop-blur transition-shadow ${
          scrolled ? "shadow-[0_1px_0_0_var(--color-line)]" : "border-b border-line"
        }`}
      >
        <div className="mx-auto flex max-w-[1400px] items-center gap-4 px-4 py-4 sm:px-6 lg:px-8">
          {/* Mobile menu trigger */}
          <button
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
            className="-ml-2 grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface lg:hidden"
          >
            <MenuIcon />
          </button>

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
          <nav className="hidden flex-1 items-center gap-6 lg:flex">
            {taxonomy.primary_nav.slice(0, 5).map((cat) => (
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
            <button
              aria-label="Search"
              className="grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
            >
              <SearchIcon />
            </button>
            <button
              onClick={open}
              aria-label={`Open bag, ${count} items`}
              className="relative grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
            >
              <BagIcon />
              {count > 0 && (
                <span className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-green-deep px-1 text-[11px] font-semibold text-paper tabular-nums">
                  {count}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Mobile menu */}
      <div
        className={`fixed inset-0 z-[90] lg:hidden ${mobileOpen ? "" : "pointer-events-none"}`}
        aria-hidden={!mobileOpen}
      >
        <div
          onClick={() => setMobileOpen(false)}
          className={`absolute inset-0 bg-ink/50 transition-opacity ${
            mobileOpen ? "opacity-100" : "opacity-0"
          }`}
        />
        <div
          className={`absolute left-0 top-0 flex h-full w-[85%] max-w-sm flex-col bg-paper transition-transform duration-300 ${
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <span className="display text-xl">Menu</span>
            <button
              onClick={() => setMobileOpen(false)}
              aria-label="Close menu"
              className="-mr-2 grid h-10 w-10 place-items-center rounded-full hover:bg-surface"
            >
              <CloseIcon />
            </button>
          </div>
          <nav className="flex-1 overflow-y-auto px-5 py-4">
            <p className="eyebrow mb-2 text-subtle">Shop</p>
            <ul className="mb-6 space-y-1">
              {taxonomy.primary_nav.map((cat) => (
                <li key={cat.id}>
                  <Link
                    href={`/shop/${cat.id}`}
                    onClick={() => setMobileOpen(false)}
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
                  <Link
                    href={c.href}
                    onClick={() => setMobileOpen(false)}
                    className="block py-2 text-lg font-medium"
                  >
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
            <p className="eyebrow mb-2 text-subtle">Clubs &amp; Teams</p>
            <ul className="space-y-1">
              {clubLinks.map((c) => (
                <li key={c.href}>
                  <Link
                    href={c.href}
                    onClick={() => setMobileOpen(false)}
                    className="block py-2 text-lg font-medium"
                  >
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </div>

      <CartDrawer />
    </>
  );
}
