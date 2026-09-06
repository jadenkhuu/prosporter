"use client";

import { useEffect } from "react";

/**
 * Swaps the sticky header's bottom border for a shadow once the page has
 * scrolled. It renders nothing and never sets React state: it toggles
 * `data-scrolled` on `<html>` and CSS in `globals.css` does the rest, so the
 * header markup itself can stay a server component (QA defect D3) and a scroll
 * event never re-renders it.
 */
export function HeaderScrollShadow() {
  useEffect(() => {
    const root = document.documentElement;
    const onScroll = () => {
      const scrolled = window.scrollY > 8;
      if (scrolled) root.setAttribute("data-scrolled", "");
      else root.removeAttribute("data-scrolled");
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      root.removeAttribute("data-scrolled");
    };
  }, []);

  return null;
}
