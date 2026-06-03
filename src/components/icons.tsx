/* Lightweight inline SVG icon set (Lucide-style, 1.6 stroke) — no emoji, themeable via currentColor. */
type IconProps = React.SVGProps<SVGSVGElement>;

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const BagIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M6 8h12l-1 12H7L6 8Z" />
    <path d="M9 8V6a3 3 0 0 1 6 0v2" />
  </svg>
);

export const MenuIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M3 6h18M3 12h18M3 18h18" />
  </svg>
);

export const CloseIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);

export const SearchIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.2-3.2" />
  </svg>
);

export const FilterIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M3 5h18M6 12h12M10 19h4" />
  </svg>
);

export const ChevronDown = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

export const ArrowRight = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const PlusIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const MinusIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="M5 12h14" />
  </svg>
);

export const CheckIcon = (p: IconProps) => (
  <svg {...base} {...p} aria-hidden>
    <path d="m5 12 5 5L20 7" />
  </svg>
);
