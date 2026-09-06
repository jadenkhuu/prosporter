"use client";

import { useCallback, useRef } from "react";
import { CloseIcon } from "@/components/icons";
import { useModalDialog } from "@/lib/hooks/useModalDialog";
import {
  MOBILE_MENU_ID,
  MOBILE_MENU_TITLE_ID,
  closeMobileMenu,
  mobileMenuOpenerRef,
  useMobileMenuOpen,
} from "./mobile-menu";

/**
 * The off-canvas menu itself: still a real modal dialog (focus in, Tab trapped,
 * Escape closes, body scroll locked, background inert, focus returned to the
 * hamburger) — only the *chrome* is client now.
 *
 * `children` is the nav markup, rendered on the server by `Header`, so the
 * category/collection/club lists and the taxonomy they come from never reach
 * the browser as JavaScript. Link clicks are caught by one delegated handler on
 * the panel instead of an `onClick` per link, which is what lets those links
 * stay server markup.
 */
export function MobileMenuPanel({ children }: { children: React.ReactNode }) {
  const open = useMobileMenuOpen();

  const rootRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const close = useCallback(() => closeMobileMenu(), []);

  useModalDialog({
    open,
    panelRef,
    rootRef,
    openerRef: mobileMenuOpenerRef,
    onClose: close,
    inertSiblings: true,
  });

  /** Following any link inside the panel dismisses it. */
  const onPanelClick = (event: React.MouseEvent<HTMLElement>) => {
    if (event.target instanceof Element && event.target.closest("a[href]")) close();
  };

  return (
    <div
      ref={rootRef}
      className={`fixed inset-0 z-[90] lg:hidden ${open ? "" : "pointer-events-none"}`}
      inert={!open}
    >
      <div
        onClick={close}
        aria-hidden="true"
        className={`absolute inset-0 bg-ink/50 transition-opacity ${
          open ? "opacity-100" : "opacity-0"
        }`}
      />
      <div
        id={MOBILE_MENU_ID}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={MOBILE_MENU_TITLE_ID}
        tabIndex={-1}
        onClick={onPanelClick}
        className={`absolute left-0 top-0 flex h-full w-[85%] max-w-sm flex-col bg-paper outline-none transition-transform duration-300 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="display text-xl" id={MOBILE_MENU_TITLE_ID}>
            Menu
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close menu"
            className="-mr-2 grid h-10 w-10 place-items-center rounded-full hover:bg-surface"
          >
            <CloseIcon />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
