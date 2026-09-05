import type { Metadata } from "next";
import { Archivo, Inter } from "next/font/google";
import "./globals.css";
import { CartProvider } from "@/components/cart/CartProvider";
import { isShopifyConfigured } from "@/lib/shopify";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";

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

export const metadata: Metadata = {
  title: "ProSporter — Volleyball Teamwear & Apparel",
  description:
    "Indoor and beach volleyball apparel, club teamwear and protective gear. Built for the Australian game.",
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
        <CartProvider enabled={cartEnabled}>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </CartProvider>
      </body>
    </html>
  );
}
