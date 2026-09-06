"use client";

import dynamic from "next/dynamic";

/**
 * The cart drawer is ~480 lines of client component — line list, quantity
 * controls, free-shipping bar, discount form — and it is closed on every first
 * paint. Loading it in its own chunk after hydration keeps it off the critical
 * path that the LCP paint waits behind (QA defect D3) without changing when it
 * is *mounted*: it is still in the tree well before any shopper can click the
 * bag or a quick-add button, so the modal behaviour (focus in, focus back to
 * the opener) is unchanged.
 *
 * `ssr: false` is what puts it in a separate chunk; the drawer is `inert` while
 * closed, so leaving its markup out of the server HTML costs nothing.
 */
const CartDrawer = dynamic(() => import("./CartDrawer").then((m) => m.CartDrawer), {
  ssr: false,
});

export function CartDrawerMount() {
  return <CartDrawer />;
}
