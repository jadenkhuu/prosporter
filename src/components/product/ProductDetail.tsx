"use client";

import { useState } from "react";
import Image from "next/image";
import {
  findVariant,
  isSizeOption,
  type CatalogProductDetail,
} from "@/lib/catalog-view";
import { formatPrice, formatPriceRange, swatchFor } from "@/lib/format";
import { useCart } from "@/components/cart/CartProvider";
import { PLACEHOLDER_IMAGE } from "@/components/product/ProductCard";
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

export function ProductDetail({ product }: { product: CatalogProductDetail }) {
  const { add, addVariant, isPending } = useCart();
  const [selection, setSelection] = useState<Record<string, string>>({});
  // Null until the shopper picks a thumbnail; a variant image wins until then.
  const [pickedImage, setPickedImage] = useState<number | null>(null);
  const [added, setAdded] = useState(false);
  const [error, setError] = useState(false);

  const variant = findVariant(product, selection);
  const needsSelection = product.options.length > 0;
  const complete = product.options.every((o) => selection[o.name]);
  const images = product.images.length ? product.images : product.image ? [product.image] : [];
  const hero =
    (pickedImage === null ? variant?.image : null) ?? images[pickedImage ?? 0] ?? images[0] ?? null;

  const price = variant?.price ?? product.price;
  const compareAt = variant?.compareAtPrice ?? product.compareAtPrice;
  const inStock = variant ? variant.available : product.inStock;
  const sizeOption = product.options.find((o) => isSizeOption(o.name));

  const choose = (option: string, value: string) => {
    setSelection((s) => ({ ...s, [option]: value }));
    setPickedImage(null);
    setError(false);
  };

  const handleAdd = () => {
    if (needsSelection && !complete) {
      setError(true);
      return;
    }
    const variantId = variant?.id ?? product.variantId;
    if (variantId) {
      addVariant(variantId);
    } else {
      // Mock catalog: no Shopify variant to add, so the drawer shim runs.
      add({
        slug: product.handle,
        name: product.title,
        price,
        image: hero?.url ?? PLACEHOLDER_IMAGE,
        size: product.options.map((o) => selection[o.name]).filter(Boolean).join(" / ") || null,
      });
    }
    setAdded(true);
    setTimeout(() => setAdded(false), 1600);
  };

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:gap-14">
      {/* Gallery */}
      <div>
        <div className="relative aspect-[4/5] overflow-hidden rounded-card bg-surface">
          <Image
            src={hero?.url ?? PLACEHOLDER_IMAGE}
            alt={hero?.alt ?? product.title}
            fill
            priority
            sizes="(max-width: 1024px) 100vw, 50vw"
            className="object-cover"
          />
          {product.onSale && (
            <span className="absolute left-4 top-4 rounded-full bg-green-deep px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-paper">
              Sale
            </span>
          )}
        </div>
        {images.length > 1 && (
          <div className="mt-3 flex gap-3 overflow-x-auto pb-1">
            {images.map((img, i) => (
              <button
                key={img.url}
                onClick={() => setPickedImage(i)}
                aria-label={`View image ${i + 1}`}
                aria-pressed={hero?.url === img.url}
                className={`relative aspect-[4/5] w-20 shrink-0 overflow-hidden rounded-card bg-surface ring-inset transition-all ${
                  hero?.url === img.url ? "ring-2 ring-ink" : "ring-1 ring-line hover:ring-muted"
                }`}
              >
                <Image src={img.url} alt="" fill sizes="80px" className="object-cover" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Info */}
      <div className="lg:py-2">
        <p className="eyebrow text-subtle">{product.categoryLabel}</p>
        <h1 className="mt-2 display text-3xl sm:text-4xl">{product.title}</h1>
        <p className="mt-4 flex items-baseline gap-3 text-2xl font-semibold tabular-nums">
          <span>
            {variant
              ? formatPrice(price, product.currency)
              : formatPriceRange(product.price, product.maxPrice, product.currency)}
          </span>
          {compareAt != null && compareAt > price && (
            <span className="text-base font-normal text-subtle line-through">
              {formatPrice(compareAt, product.currency)}
            </span>
          )}
        </p>

        {/* Tags */}
        <div className="mt-4 flex flex-wrap gap-2">
          {product.surface && (
            <span className="rounded-full border border-line px-3 py-1 text-xs font-medium capitalize text-muted">
              {product.surface}
            </span>
          )}
          {product.gender
            .filter((g) => g.toLowerCase() !== "unisex")
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
              inStock ? "bg-green-deep/10 text-green-deep" : "bg-surface-2 text-muted"
            }`}
          >
            {inStock ? "In stock" : "Sold out"}
          </span>
        </div>

        {/* Options — a simple product has none and shows no selector */}
        {product.options.map((option) => {
          const swatches = product.colours.length > 0 && option.values.every((v) => product.colours.includes(v));
          return (
            <div key={option.name} className="mt-6">
              <div className="mb-2 flex items-center justify-between">
                <p className="eyebrow text-ink">
                  {option.name}
                  {selection[option.name] && (
                    <span className="text-subtle"> · {selection[option.name]}</span>
                  )}
                </p>
                {isSizeOption(option.name) && (
                  <button className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline">
                    Size guide
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {option.values.map((value) => {
                  const active = selection[option.name] === value;
                  return swatches ? (
                    <button
                      key={value}
                      onClick={() => choose(option.name, value)}
                      title={value}
                      aria-label={value}
                      aria-pressed={active}
                      className={`h-8 w-8 rounded-full ring-inset transition-all ${
                        active
                          ? "ring-2 ring-ink ring-offset-2 ring-offset-paper"
                          : "ring-1 ring-line hover:ring-muted"
                      }`}
                      style={{ background: swatchFor(value) }}
                    />
                  ) : (
                    <button
                      key={value}
                      onClick={() => choose(option.name, value)}
                      aria-pressed={active}
                      className={`min-w-[52px] rounded-md border px-3 py-2.5 text-sm font-medium transition-colors ${
                        active
                          ? "border-ink bg-ink text-paper"
                          : "border-line bg-paper text-ink hover:border-muted"
                      }`}
                    >
                      {value}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
        {error && (
          <p role="alert" className="mt-2 text-xs font-medium text-[#c0392b]">
            Please choose {product.options.map((o) => o.name.toLowerCase()).join(" and ")} before
            adding to bag.
          </p>
        )}

        {/* Add to cart */}
        <button
          onClick={handleAdd}
          disabled={!inStock || isPending}
          className={`mt-7 flex w-full items-center justify-center gap-2 rounded-full px-6 py-4 text-sm font-semibold transition-colors ${
            !inStock
              ? "cursor-not-allowed bg-surface-2 text-subtle"
              : added
                ? "bg-green-deep text-paper"
                : "bg-ink text-paper hover:bg-ink-2"
          }`}
        >
          {!inStock ? (
            "Sold out"
          ) : isPending ? (
            "Adding…"
          ) : added ? (
            <>
              <CheckIcon width={18} height={18} /> Added to bag
            </>
          ) : (
            `Add to bag · ${formatPrice(price, product.currency)}`
          )}
        </button>

        {/* Details */}
        <div className="mt-8">
          <Accordion title="Product details">
            {product.descriptionHtml ? (
              <div
                className="product-description"
                dangerouslySetInnerHTML={{ __html: product.descriptionHtml }}
              />
            ) : (
              <p>{product.description || product.seo.description || product.title}</p>
            )}
          </Accordion>
          {product.details.personalisation && (
            <Accordion title="Personalisation">
              {product.details.personalisation.join(", ")}
            </Accordion>
          )}
          <Accordion title="Shipping &amp; returns">
            Free standard shipping on orders over $150. Easy 30-day returns on
            unworn items with tags attached. Checkout is securely completed on
            prosporter.com.au.
          </Accordion>
          <Accordion title="Sizing">
            {product.details.size_guide ? (
              product.details.size_guide.join(" ")
            ) : (
              <>
                Available sizes:{" "}
                {sizeOption ? sizeOption.values.join(", ") : "One size"}. Not sure? Check the size
                guide above or get in touch with the team.
              </>
            )}
          </Accordion>
        </div>
      </div>
    </div>
  );
}
