export function formatPrice(amount: number, currency = "AUD"): string {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(amount);
}

/**
 * Price label for a product whose variants span a range. Collapses to a single
 * price when min and max match, which is the common case.
 */
export function formatPriceRange(min: number, max: number, currency = "AUD"): string {
  return max > min
    ? `${formatPrice(min, currency)} – ${formatPrice(max, currency)}`
    : formatPrice(min, currency);
}

/** Map a colour name to a swatch fill. Falls back to a neutral grey. */
export const COLOUR_SWATCHES: Record<string, string> = {
  Navy: "#1f2a44",
  Black: "#181817",
  White: "#ffffff",
  Yellow: "#f2c200",
  Grey: "#9aa0a6",
  Red: "#c0392b",
  "Royal Blue": "#2d57c4",
  Blue: "#2f6fed",
  Orange: "#e8772e",
  Green: "#638d50",
  "Sky Blue": "#7fc4e8",
};

export function swatchFor(colour: string): string {
  return COLOUR_SWATCHES[colour] ?? "#c8ccc4";
}
