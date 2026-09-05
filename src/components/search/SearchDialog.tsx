"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SearchIcon, CloseIcon } from "@/components/icons";

/**
 * Header search: an icon trigger plus a modal search panel.
 *
 * The panel stays in the DOM (so the form is server-rendered and works before
 * hydration) but is `inert` while closed, which removes it from the tab order
 * and the accessibility tree. Opening moves focus into the input; closing
 * returns it to the trigger. Escape closes.
 *
 * No `setState` runs synchronously inside an effect (`react-hooks/set-state-in-effect`):
 * state only changes from click, submit and keydown handlers.
 */
export function SearchDialog() {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!open) return;

    inputRef.current?.focus();
    inputRef.current?.select();
    const trigger = triggerRef.current;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      // Focus goes back where it came from when the panel closes.
      trigger?.focus();
    };
  }, [open]);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = inputRef.current?.value.trim() ?? "";
    if (!query) {
      inputRef.current?.focus();
      return;
    }
    setOpen(false);
    router.push(`/search?q=${encodeURIComponent(query)}`);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Search products"
        aria-expanded={open}
        aria-haspopup="dialog"
        className="grid h-10 w-10 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
      >
        <SearchIcon />
      </button>

      <div
        className={`fixed inset-0 z-[95] ${open ? "" : "pointer-events-none"}`}
        inert={!open}
        aria-hidden={!open}
      >
        <div
          onClick={() => setOpen(false)}
          className={`absolute inset-0 bg-ink/50 transition-opacity ${
            open ? "opacity-100" : "opacity-0"
          }`}
        />
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Search products"
          className={`absolute inset-x-0 top-0 border-b border-line bg-paper transition-transform duration-200 ${
            open ? "translate-y-0" : "-translate-y-full"
          }`}
        >
          <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-4 sm:px-6 lg:px-8">
            <form role="search" action="/search" onSubmit={onSubmit} className="flex-1">
              <label htmlFor="header-search-input" className="sr-only">
                Search products
              </label>
              <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2.5 focus-within:border-ink">
                <SearchIcon className="shrink-0 text-muted" />
                <input
                  ref={inputRef}
                  id="header-search-input"
                  type="search"
                  name="q"
                  placeholder="Search jerseys, shorts, clubs…"
                  autoComplete="off"
                  className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-subtle"
                />
                <button
                  type="submit"
                  className="shrink-0 rounded-full bg-ink px-4 py-1.5 text-sm font-semibold text-paper hover:bg-ink-2"
                >
                  Search
                </button>
              </div>
            </form>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close search"
              className="-mr-2 grid h-10 w-10 shrink-0 place-items-center rounded-full text-ink transition-colors hover:bg-surface"
            >
              <CloseIcon />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
