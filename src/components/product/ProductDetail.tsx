"use client";

import { useState } from "react";
import Image from "next/image";
import type { Product } from "@/lib/catalog";
import { getCategoryLabel } from "@/lib/catalog";
import { formatPrice, swatchFor } from "@/lib/format";
import { useCart } from "@/components/cart/CartProvider";
import { CheckIcon, ChevronDown } from "@/components/icons";

function Accordion({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-line">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between py-4 text-left"
        aria-expanded={open}
      >
        <span className="text-sm font-semibold text-ink">{title}</span>
        <ChevronDown
          width={18}
          height={18}
          className={`text-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="pb-4 text-sm leading-relaxed text-muted">{children}</div>}
    </div>
  );
}

export function ProductDetail({ product }: { product: Product }) {
  const { add } = useCart();
  const hasSizes = product.sizes.length > 0;
  const [size, setSize] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [error, setError] = useState(false);

  const handleAdd = () => {
    if (hasSizes && !size) {
      setError(true);
      return;
    }
    add({
      slug: product.slug,
      name: product.name,
      price: product.price,
      image: product.image_local,
      size,
    });
    setAdded(true);
    setTimeout(() => setAdded(false), 1600);
  };

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:gap-14">
      {/* Gallery */}
      <div className="relative aspect-[4/5] overflow-hidden rounded-card bg-surface">
        <Image
          src={product.image_local}
          alt={product.name}
          fill
          priority
          sizes="(max-width: 1024px) 100vw, 50vw"
          className="object-cover"
        />
        {product.on_sale && (
          <span className="absolute left-4 top-4 rounded-full bg-green-deep px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-paper">
            Sale
          </span>
        )}
      </div>

      {/* Info */}
      <div className="lg:py-2">
        <p className="eyebrow text-subtle">{getCategoryLabel(product.primary_category)}</p>
        <h1 className="mt-2 display text-3xl sm:text-4xl">{product.name}</h1>
        <p className="mt-4 text-2xl font-semibold tabular-nums">
          {formatPrice(product.price)}
        </p>

        {/* Tags */}
        <div className="mt-4 flex flex-wrap gap-2">
          {product.surface && (
            <span className="rounded-full border border-line px-3 py-1 text-xs font-medium capitalize text-muted">
              {product.surface}
            </span>
          )}
          {product.gender
            .filter((g) => g !== "unisex")
            .map((g) => (
              <span
                key={g}
                className="rounded-full border border-line px-3 py-1 text-xs font-medium capitalize text-muted"
              >
                {g}
              </span>
            ))}
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              product.in_stock
                ? "bg-green-deep/10 text-green-deep"
                : "bg-surface-2 text-muted"
            }`}
          >
            {product.in_stock ? "In stock" : "Sold out"}
          </span>
        </div>

        {/* Colours */}
        {product.colours.length > 0 && (
          <div className="mt-6">
            <p className="eyebrow mb-2 text-ink">
              Colour <span className="text-subtle">· {product.colours.join(", ")}</span>
            </p>
            <div className="flex gap-2">
              {product.colours.map((c) => (
                <span
                  key={c}
                  title={c}
                  className="h-8 w-8 rounded-full ring-1 ring-line ring-inset"
                  style={{ background: swatchFor(c) }}
                />
              ))}
            </div>
          </div>
        )}

        {/* Sizes */}
        {hasSizes && (
          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between">
              <p className="eyebrow text-ink">Size</p>
              <button className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline">
                Size guide
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {product.sizes.map((s) => {
                const active = size === s;
                return (
                  <button
                    key={s}
                    onClick={() => {
                      setSize(s);
                      setError(false);
                    }}
                    aria-pressed={active}
                    className={`min-w-[52px] rounded-md border px-3 py-2.5 text-sm font-medium transition-colors ${
                      active
                        ? "border-ink bg-ink text-paper"
                        : "border-line bg-paper text-ink hover:border-muted"
                    }`}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
            {error && (
              <p role="alert" className="mt-2 text-xs font-medium text-[#c0392b]">
                Please select a size before adding to bag.
              </p>
            )}
          </div>
        )}

        {/* Add to cart */}
        <button
          onClick={handleAdd}
          disabled={!product.in_stock}
          className={`mt-7 flex w-full items-center justify-center gap-2 rounded-full px-6 py-4 text-sm font-semibold transition-colors ${
            !product.in_stock
              ? "cursor-not-allowed bg-surface-2 text-subtle"
              : added
                ? "bg-green-deep text-paper"
                : "bg-ink text-paper hover:bg-ink-2"
          }`}
        >
          {!product.in_stock ? (
            "Sold out"
          ) : added ? (
            <>
              <CheckIcon width={18} height={18} /> Added to bag
            </>
          ) : (
            `Add to bag · ${formatPrice(product.price)}`
          )}
        </button>

        {/* Details */}
        <div className="mt-8">
          <Accordion title="Product details">
            <p>
              {product.name} from the ProSporter range. Performance volleyball
              apparel designed for {product.surface ?? "training and match"} play,
              built to move with you and hold up season after season.
            </p>
          </Accordion>
          <Accordion title="Shipping &amp; returns">
            Free standard shipping on orders over $150. Easy 30-day returns on
            unworn items with tags attached. Checkout is securely completed on
            prosporter.com.au.
          </Accordion>
          <Accordion title="Sizing">
            Available sizes:{" "}
            {hasSizes ? product.sizes.join(", ") : "One size"}. Not sure? Check the
            size guide above or get in touch with the team.
          </Accordion>
        </div>
      </div>
    </div>
  );
}
