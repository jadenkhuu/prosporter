"use client";

import { useCart } from "./CartProvider";
import { BagIcon } from "@/components/icons";

/**
 * Header bag button. A client island because it reads the live line count from
 * `CartProvider` and opens the drawer; everything around it in the header is
 * server-rendered (QA defect D3).
 */
export function CartButton() {
  const { count, open } = useCart();
  return (
    <button
      onClick={open}
      aria-label={`Open bag, ${count} items`}
      className="relative grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
    >
      <BagIcon />
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-green-deep px-1 text-[11px] font-semibold text-paper tabular-nums">
          {count}
        </span>
      )}
    </button>
  );
}
