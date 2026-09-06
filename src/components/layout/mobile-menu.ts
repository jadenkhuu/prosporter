"use client";

import { useSyncExternalStore } from "react";

/**
 * Open/closed state for the mobile menu, held outside React so the two halves
 * of the menu can be separate client islands inside a *server* header.
 *
 * The hamburger sits in the header bar; the dialog has to stay a direct child
 * of `<body>` (its `inertSiblings` treatment inerts the header, main and
 * footer). Before this split both lived in one `"use client"` Header, which
 * pulled the whole nav — and `mock-data/catalog.json`, 58 KB of it, via
 * `@/lib/catalog` — into the client bundle on every route (QA defect D3).
 *
 * `useSyncExternalStore` rather than `useState` + an effect keeps
 * `react-hooks/set-state-in-effect` satisfied: nothing sets state on mount, and
 * the server snapshot is always "closed".
 */

export const MOBILE_MENU_ID = "mobile-menu";
export const MOBILE_MENU_TITLE_ID = "mobile-menu-title";

let open = false;
const listeners = new Set<() => void>();

/**
 * The control focus returns to when the menu closes. A stable object, not a
 * React ref, so both islands can share it without re-running the modal effect.
 */
export const mobileMenuOpenerRef: { current: HTMLElement | null } = { current: null };

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const getSnapshot = () => open;
/** Server render is always the closed state; the panel is `inert` there. */
const getServerSnapshot = () => false;

export function openMobileMenu(opener: HTMLElement | null): void {
  mobileMenuOpenerRef.current = opener;
  if (open) return;
  open = true;
  emit();
}

export function closeMobileMenu(): void {
  if (!open) return;
  open = false;
  emit();
}

export function useMobileMenuOpen(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
