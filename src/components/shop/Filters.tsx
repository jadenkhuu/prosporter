"use client";

import { useId, useState } from "react";
import type { Facets } from "@/lib/catalog-view";
import { swatchFor } from "@/lib/format";
import { formatPrice } from "@/lib/format";
import { ChevronDown, CheckIcon } from "@/components/icons";

export type FilterState = {
  gender: string[];
  surface: string[];
  colour: string[];
  size: string[];
  maxPrice: number | null;
  inStock: boolean;
  onSale: boolean;
};

export const emptyFilters: FilterState = {
  gender: [],
  surface: [],
  colour: [],
  size: [],
  maxPrice: null,
  inStock: false,
  onSale: false,
};

/**
 * One collapsible filter group. It is a real `<fieldset>` so assistive tech
 * announces "Colour, group" around the controls, and the disclosure button
 * lives in the `<legend>` with `aria-expanded` / `aria-controls`.
 */
function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = `filter-panel-${useId()}`;
  return (
    <fieldset className="w-full border-b border-line py-4">
      <legend className="w-full">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between"
          aria-expanded={open}
          aria-controls={panelId}
        >
          <span className="eyebrow text-ink">{title}</span>
          <ChevronDown
            width={16}
            height={16}
            aria-hidden="true"
            className={`text-muted transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </legend>
      <div id={panelId} hidden={!open} className="mt-3">
        {children}
      </div>
    </fieldset>
  );
}

const GENDER_LABELS: Record<string, string> = {
  men: "Men",
  women: "Women",
  unisex: "Unisex",
};
const SURFACE_LABELS: Record<string, string> = {
  beach: "Beach",
  indoor: "Indoor",
};

/**
 * Checkbox row. The real `<input type="checkbox">` carries the state and the
 * keyboard behaviour; it is visually hidden and the styled box mirrors it via
 * Tailwind `peer-*` variants, including the focus ring.
 */
function Check({
  checked,
  label,
  count,
  onChange,
}: {
  checked: boolean;
  label: string;
  count?: number;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2.5 py-1.5 text-sm">
      <input type="checkbox" checked={checked} onChange={onChange} className="peer sr-only" />
      <span
        aria-hidden="true"
        className={`grid h-[18px] w-[18px] place-items-center rounded border transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green-deep ${
          checked ? "border-ink bg-ink text-paper" : "border-line bg-paper"
        }`}
      >
        {checked && <CheckIcon width={12} height={12} />}
      </span>
      <span className="flex-1 text-ink">{label}</span>
      {count != null && <span className="text-xs text-subtle tabular-nums">{count}</span>}
    </label>
  );
}

/** Colour swatch as a checkbox: hidden input + styled label, same look as before. */
function SwatchCheck({
  value,
  count,
  checked,
  onChange,
}: {
  value: string;
  count: number;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="cursor-pointer" title={`${value} (${count})`}>
      <input type="checkbox" checked={checked} onChange={onChange} className="peer sr-only" />
      <span className="sr-only">{`${value} (${count} products)`}</span>
      <span
        aria-hidden="true"
        className={`block h-7 w-7 rounded-full ring-inset transition-all peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green-deep ${
          checked
            ? "ring-2 ring-ink ring-offset-2 ring-offset-paper"
            : "ring-1 ring-line hover:ring-muted"
        }`}
        style={{ background: swatchFor(value) }}
      />
    </label>
  );
}

/** Size chip as a checkbox: hidden input + styled label. */
function SizeCheck({
  value,
  checked,
  onChange,
}: {
  value: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="cursor-pointer">
      <input type="checkbox" checked={checked} onChange={onChange} className="peer sr-only" />
      <span
        className={`block min-w-[44px] rounded border px-2 py-1.5 text-center text-xs font-medium transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-green-deep ${
          checked
            ? "border-ink bg-ink text-paper"
            : "border-line bg-paper text-ink hover:border-muted"
        }`}
      >
        {value}
      </span>
    </label>
  );
}

export function Filters({
  facets,
  value,
  onChange,
}: {
  facets: Facets;
  value: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const priceId = `filter-price-${useId()}`;
  const toggle = (key: "gender" | "surface" | "colour" | "size", v: string) => {
    const arr = value[key];
    onChange({
      ...value,
      [key]: arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v],
    });
  };

  return (
    <div>
      <Section title="Availability">
        <Check
          checked={value.inStock}
          label="In stock"
          onChange={() => onChange({ ...value, inStock: !value.inStock })}
        />
        <Check
          checked={value.onSale}
          label="On sale"
          onChange={() => onChange({ ...value, onSale: !value.onSale })}
        />
      </Section>

      {facets.gender.length > 1 && (
        <Section title="Gender">
          {facets.gender.map((g) => (
            <Check
              key={g.value}
              checked={value.gender.includes(g.value)}
              label={GENDER_LABELS[g.value] ?? g.value}
              count={g.count}
              onChange={() => toggle("gender", g.value)}
            />
          ))}
        </Section>
      )}

      {facets.surface.length > 1 && (
        <Section title="Surface">
          {facets.surface.map((s) => (
            <Check
              key={s.value}
              checked={value.surface.includes(s.value)}
              label={SURFACE_LABELS[s.value] ?? s.value}
              count={s.count}
              onChange={() => toggle("surface", s.value)}
            />
          ))}
        </Section>
      )}

      {facets.colour.length > 0 && (
        <Section title="Colour">
          <div className="flex flex-wrap gap-2">
            {facets.colour.map((c) => (
              <SwatchCheck
                key={c.value}
                value={c.value}
                count={c.count}
                checked={value.colour.includes(c.value)}
                onChange={() => toggle("colour", c.value)}
              />
            ))}
          </div>
        </Section>
      )}

      {facets.size.length > 0 && (
        <Section title="Size">
          <div className="flex flex-wrap gap-2">
            {facets.size.map((s) => (
              <SizeCheck
                key={s.value}
                value={s.value}
                checked={value.size.includes(s.value)}
                onChange={() => toggle("size", s.value)}
              />
            ))}
          </div>
        </Section>
      )}

      <Section title="Price">
        <div className="px-0.5">
          <label className="sr-only" htmlFor={priceId}>
            Maximum price
          </label>
          <input
            id={priceId}
            type="range"
            min={facets.priceMin}
            max={facets.priceMax}
            value={value.maxPrice ?? facets.priceMax}
            aria-valuetext={formatPrice(value.maxPrice ?? facets.priceMax)}
            onChange={(e) => onChange({ ...value, maxPrice: Number(e.target.value) })}
            className="w-full accent-[var(--color-green-deep)]"
          />
          <div className="mt-1 flex justify-between text-xs text-muted tabular-nums">
            <span>{formatPrice(facets.priceMin)}</span>
            <span className="font-semibold text-ink">
              Up to {formatPrice(value.maxPrice ?? facets.priceMax)}
            </span>
          </div>
        </div>
      </Section>
    </div>
  );
}
