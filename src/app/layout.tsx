import type { Metadata } from "next";
import { Archivo, Inter } from "next/font/google";
import "./globals.css";
import { CartProvider } from "@/components/cart/CartProvider";
import { isShopifyConfigured } from "@/lib/shopify";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildOrganizationJsonLd, buildWebSiteJsonLd } from "@/lib/seo/json-ld";
import { OG_DEFAULTS } from "@/lib/seo/metadata";
import { SITE_DESCRIPTION, siteUrl } from "@/lib/site";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  weight: ["600", "700", "800", "900"],
  style: ["normal", "italic"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
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
        {/* Site-wide structured data: the Organization every other node points
            at with `@id`, and the WebSite whose SearchAction advertises
            /search?q= for sitelinks. Rendered server-side, so it is in the
            initial HTML a crawler reads. */}
        <JsonLd data={[buildOrganizationJsonLd(), buildWebSiteJsonLd()]} />
        <CartProvider enabled={cartEnabled}>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </CartProvider>
      </body>
    </html>
  );
}
