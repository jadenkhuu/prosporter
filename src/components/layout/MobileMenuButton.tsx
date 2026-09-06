"use client";

import { MenuIcon } from "@/components/icons";
import { MOBILE_MENU_ID, openMobileMenu, useMobileMenuOpen } from "./mobile-menu";

/**
 * The hamburger. One of the two client islands in the otherwise server-rendered
 * header; it hands its own element to the store so focus returns here when the
 * menu closes, whether or not the browser focused it on tap.
 */
export function MobileMenuButton() {
  const open = useMobileMenuOpen();
  return (
    <button
      type="button"
      onClick={(event) => openMobileMenu(event.currentTarget)}
      aria-label="Open menu"
      aria-expanded={open}
      aria-controls={MOBILE_MENU_ID}
      className="-ml-2 grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface lg:hidden"
    >
      <MenuIcon />
    </button>
  );
}
