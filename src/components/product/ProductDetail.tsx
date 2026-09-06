"use client";

import { useEffect, useId, useRef, useState } from "react";
import Image from "next/image";
import {
  findVariant,
  isSizeOption,
  type CatalogProductDetail,
} from "@/lib/catalog-view";
import { formatPrice, formatPriceRange, swatchFor } from "@/lib/format";
import { useCart } from "@/components/cart/CartProvider";
import { track, viewItemParams } from "@/lib/analytics";
import { PLACEHOLDER_IMAGE } from "@/components/product/ProductCard";
import { CheckIcon, ChevronDown } from "@/components/icons";

/** Disclosure: button and panel wired together with aria-expanded/controls. */
function Accordion({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const uid = useId();
  const buttonId = `accordion-button-${uid}`;
  const panelId = `accordion-panel-${uid}`;
  return (
    <div className="border-b border-line">
      <h2>
        <button
          type="button"
          id={buttonId}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between py-4 text-left"
          aria-expanded={open}
          aria-controls={panelId}
        >
          <span className="text-sm font-semibold text-ink">{title}</span>
          <ChevronDown
            width={18}
            height={18}
            aria-hidden="true"
            className={`text-muted transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </h2>
      <div
        id={panelId}
        role="region"
        aria-labelledby={buttonId}
        hidden={!open}
        className="pb-4 text-sm leading-relaxed text-muted"
      >
        {children}
      </div>
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
  const uid = useId();
  const errorId = `pdp-error-${uid}`;

  /**
   * GA4 view_item (CLNT-179): once per product, not once per variant click.
   * The handle in a ref is what makes that true — the effect re-runs on a
   * client-side navigation to another product (same component instance, new
   * props) but not on a size or colour change, and Strict Mode's double
   * invocation in development sends nothing extra. A single-variant product
   * reports that variant so `item_id` is its SKU; a multi-variant one reports
   * product-level identity, because no variant has been chosen yet.
   */
  const viewedHandle = useRef<string | null>(null);
  useEffect(() => {
    if (viewedHandle.current === product.handle) return;
    viewedHandle.current = product.handle;
    track(
      "view_item",
      viewItemParams(product, product.variants.length === 1 ? product.variants[0] : null),
    );
  }, [product]);

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

  /** Does any purchasable variant carry this option value? */
  const valueAvailable = (optionName: string, value: string) => {
    if (product.variants.length === 0) return true;
    return product.variants.some(
      (v) =>
        v.available &&
        v.selectedOptions.some((o) => o.name === optionName && o.value === value),
    );
  };

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

  // Announced when the shopper's selection changes the price or availability.
  const selectionStatus = variant
    ? `${variant.title === product.title ? "Selected" : variant.title}: ${formatPrice(
        price,
        product.currency,
      )}, ${variant.available ? "in stock" : "sold out"}.`
    : needsSelection
      ? "No variant selected yet."
      : `${formatPrice(price, product.currency)}, ${inStock ? "in stock" : "sold out"}.`;

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:gap-14">
      {/* Gallery */}
      <div>
        <div className="relative aspect-[4/5] overflow-hidden rounded-card bg-surface">
          <Image
            src={hero?.url ?? PLACEHOLDER_IMAGE}
            alt={hero ? hero.alt || product.title : "No photo available yet"}
            fill
            unoptimized={!hero}
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
          <ul
            aria-label={`${product.title} images`}
            className="mt-3 flex gap-3 overflow-x-auto pb-1"
          >
            {images.map((img, i) => {
              const current = hero?.url === img.url;
              return (
                <li key={img.url} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => setPickedImage(i)}
                    aria-label={`Show image ${i + 1} of ${images.length}${
                      img.alt ? `: ${img.alt}` : ""
                    }`}
                    aria-current={current ? "true" : undefined}
                    aria-pressed={current}
                    className={`relative block aspect-[4/5] w-20 shrink-0 overflow-hidden rounded-card bg-surface ring-inset transition-all ${
                      current ? "ring-2 ring-ink" : "ring-1 ring-line hover:ring-muted"
                    }`}
                  >
                    <Image src={img.url} alt="" fill sizes="80px" className="object-cover" />
                  </button>
                </li>
              );
            })}
          </ul>
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
              <span className="sr-only">Was </span>
              {formatPrice(compareAt, product.currency)}
            </span>
          )}
        </p>

        {/* Price / availability for the current selection. */}
        <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {selectionStatus}
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

        {/* Options — a simple product has none and shows no selector.
            Each option is a radio group: one tab stop, arrow keys move between
            values, and the inputs are visually hidden behind styled labels. */}
        {product.options.map((option, optionIndex) => {
          const swatches =
            product.colours.length > 0 && option.values.every((v) => product.colours.includes(v));
          const groupName = `option-${uid}-${optionIndex}`;
          return (
            <fieldset key={option.name} className="mt-6">
              {/* Visually hidden legend names the group; the visible heading is
                  aria-hidden so the option name is not announced twice. */}
              <legend className="sr-only">{option.name}</legend>
              <div className="mb-2 flex items-center justify-between">
                <p className="eyebrow text-ink" aria-hidden="true">
                  {option.name}
                  {selection[option.name] && (
                    <span className="text-subtle"> · {selection[option.name]}</span>
                  )}
                </p>
                {isSizeOption(option.name) && (
                  <button
                    type="button"
                    className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
                  >
                    Size guide
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {option.values.map((value) => {
                  const active = selection[option.name] === value;
                  const soldOut = !valueAvailable(option.name, value);
                  const input = (
                    <input
                      type="radio"
                      name={groupName}
                      value={value}
                      checked={active}
                      onChange={() => choose(option.name, value)}
                      className="peer sr-only"
                    />
                  );
                  return swatches ? (
                    <label key={value} className="cursor-pointer" title={value}>
                      {input}
                      <span className="sr-only">
                        {value}
                        {soldOut ? " (sold out)" : ""}
                      </span>
                      <span
                        aria-hidden="true"
                        className={`block h-8 w-8 rounded-full ring-inset transition-all peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green-deep ${
                          active
                            ? "ring-2 ring-ink ring-offset-2 ring-offset-paper"
                            : "ring-1 ring-line hover:ring-muted"
                        } ${soldOut ? "opacity-40" : ""}`}
                        style={{ background: option.swatches?.[value] ?? swatchFor(value) }}
                      />
                    </label>
                  ) : (
                    <label key={value} className="cursor-pointer">
                      {input}
                      <span
                        className={`block min-w-[52px] rounded-md border px-3 py-2.5 text-center text-sm font-medium transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green-deep ${
                          active
                            ? "border-ink bg-ink text-paper"
                            : "border-line bg-paper text-ink hover:border-muted"
                        } ${soldOut && !active ? "text-subtle line-through" : ""}`}
                      >
                        {value}
                        {soldOut && <span className="sr-only"> (sold out)</span>}
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        })}
        {error && (
          <p id={errorId} role="alert" className="mt-2 text-xs font-medium text-[#c0392b]">
            Please choose {product.options.map((o) => o.name.toLowerCase()).join(" and ")} before
            adding to bag.
          </p>
        )}

        {/* Add to cart */}
        <button
          type="button"
          onClick={handleAdd}
          disabled={!inStock || isPending}
          aria-disabled={!inStock || isPending}
          aria-busy={isPending}
          aria-describedby={error ? errorId : undefined}
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
              <CheckIcon width={18} height={18} aria-hidden="true" /> Added to bag
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
