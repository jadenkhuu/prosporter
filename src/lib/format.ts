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
  Pink: "#e58fb5",
  Royal: "#2d57c4",
};

/**
 * Fallback swatch for a colour name when Shopify has no swatch set on the
 * option value. Two-tone names ("Black / Grey") render as a split disc.
 * Unknown names get a neutral grey rather than guessing.
 */
export function swatchFor(colour: string): string {
  const direct = COLOUR_SWATCHES[colour] ?? COLOUR_SWATCHES[titleCase(colour)];
  if (direct) return direct;
  const parts = colour.split("/").map((c) => c.trim()).filter(Boolean);
  if (parts.length === 2) {
    const [a, b] = parts.map((c) => COLOUR_SWATCHES[c] ?? COLOUR_SWATCHES[titleCase(c)]);
    if (a && b) return `linear-gradient(135deg, ${a} 50%, ${b} 50%)`;
  }
  return "#c8ccc4";
}

function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(" ")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
