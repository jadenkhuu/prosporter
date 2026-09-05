import type { Metadata } from "next";
import { Archivo, Inter } from "next/font/google";
import "./globals.css";
import { CartProvider } from "@/components/cart/CartProvider";
import { getCurrentCart } from "@/lib/shopify/cart-actions";
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

// Reading the cart cookie makes every route dynamic; that is the cost of a
// server-rendered bag count with `cacheComponents` off (CLNT-171).
export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cartEnabled = isShopifyConfigured();
  const initialCart = cartEnabled ? await getCurrentCart() : null;

  return (
    <html
      lang="en"
      className={`${archivo.variable} ${inter.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-paper text-ink">
        <CartProvider initialCart={initialCart} enabled={cartEnabled}>
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </CartProvider>
      </body>
    </html>
  );
}
