import type { Metadata } from "next";
import { Archivo, Inter } from "next/font/google";
import "./globals.css";
import { Analytics } from "@/components/analytics/Analytics";
import { CartProvider } from "@/components/cart/CartProvider";
import { isShopifyConfigured } from "@/lib/shopify";
import { AnnouncementBar } from "@/components/layout/AnnouncementBar";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildOrganizationJsonLd, buildWebSiteJsonLd } from "@/lib/seo/json-ld";
import { OG_DEFAULTS } from "@/lib/seo/metadata";
import { SITE_DESCRIPTION, siteUrl } from "@/lib/site";

/**
 * Only `.display` uses Archivo, and only at weight 800 (upright on every page,
 * italic on the home hero). Declaring the four-weight range pulled the whole
 * variable face down on every route — ~48 KB of it for the italic alone — which
 * is render-critical weight the LCP text paint waits behind (QA defect D3).
 * `display: "swap"` is next/font's default; it is spelled out here because the
 * LCP element on a product page *is* text.
 */
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  weight: ["800"],
  style: ["normal", "italic"],
  display: "swap",
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

/**
 * `metadataBase` is what lets every route write `alternates.canonical: "/shop"`
 * and have it resolve to an absolute URL. It comes from the one site-URL config
 * value (`NEXT_PUBLIC_SITE_URL`; see `src/lib/site.ts` and `docs/deployment.md`),
 * so canonicals, Open Graph URLs, `robots.txt` and `sitemap.xml` can never
 * disagree about which origin is canonical.
 */
export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: "ProSporter — Volleyball Teamwear & Apparel",
  description: SITE_DESCRIPTION,
  openGraph: {
    ...OG_DEFAULTS,
    type: "website",
    url: "/",
    title: "ProSporter — Volleyball Teamwear & Apparel",
    description: SITE_DESCRIPTION,
  },
};

// The layout deliberately does not read the cart cookie: doing so would make
// every route dynamic. CartProvider fetches the shopper's cart on mount instead,
// so product and shop pages stay prerenderable with tag-based revalidation.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cartEnabled = isShopifyConfigured();

  return (
    <html
      lang="en"
      className={`${archivo.variable} ${inter.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-paper text-ink">
        {/* Bypass Blocks (WCAG 2.4.1): first focusable element on every page,
            off-screen until it takes focus. Targets the one <main> landmark. */}
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        {/* Site-wide structured data: the Organization every other node points
            at with `@id`, and the WebSite whose SearchAction advertises
            /search?q= for sitelinks. Rendered server-side, so it is in the
            initial HTML a crawler reads. */}
        <JsonLd data={[buildOrganizationJsonLd(), buildWebSiteJsonLd()]} />
        {/* GA4 (CLNT-179). Renders nothing at all until
            NEXT_PUBLIC_GA_MEASUREMENT_ID is set, which is the state until
            cutover. See docs/deployment.md § Analytics. */}
        <Analytics />
        <CartProvider enabled={cartEnabled}>
          <AnnouncementBar />
          <Header />
          {/* tabIndex={-1} so the skip link can move real focus here, not just
              the scroll position; scroll-margin keeps it clear of the sticky
              header (2.4.11 Focus Not Obscured). */}
          <main id="main" tabIndex={-1} className="flex-1 scroll-mt-24 outline-none">
            {children}
          </main>
          <Footer />
        </CartProvider>
      </body>
    </html>
  );
}
