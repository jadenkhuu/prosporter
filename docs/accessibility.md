# Accessibility — storefront shopping flow (CLNT-171)

Scope of this pass: the cart drawer, shop filters and listing, the product card
and the product detail page, plus the shared focus styles in
`src/app/globals.css`. Header, main nav, mobile menu and the search dialog were
worked on separately and are listed under "Still to do".

Target: **WCAG 2.2 level AA**.

---

## What changed, per component

### `src/components/cart/CartDrawer.tsx`

- The panel is a real modal dialog: `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby` pointing at the "Your Bag" heading (`#cart-drawer-title`).
- **Focus in**: opening the drawer moves focus to the panel itself
  (`tabIndex={-1}`), so a screen reader announces the dialog name first.
- **Focus return**: the element that was focused when the drawer opened (the
  header bag button) is stored in `openerRef` and re-focused by the effect's
  cleanup when the drawer closes — whether it closed via Escape, the close
  button, the scrim or "Continue shopping".
- **Focus trap**: a capture-phase `keydown` listener wraps Tab / Shift+Tab
  inside the panel and pulls focus back if it escapes.
- **Escape** closes the drawer.
- **Background**: every sibling of the drawer root gets the `inert` attribute
  while it is open (removed on close), so the header, page and footer are out of
  the tab order and hidden from assistive tech. When the drawer is closed the
  root itself is `inert`, so the off-canvas controls are never tab stops.
- **Live region**: a single always-mounted `role="status" aria-live="polite"`
  node announces bag state ("2 items in your bag. Subtotal $180.00.") and any
  cart error. The visible error paragraph is `aria-hidden` so it is not read
  twice.
- **Accessible names**: quantity buttons read "Increase quantity of Ace Unisex
  Tee (Green · M)"; remove reads "Remove Ace Unisex Tee (Green · M) from bag".
  Line thumbnails are `alt=""` because the product title sits next to them.
- **Checkout** is a real `<a href>`; when no checkout URL exists yet the
  placeholder is a non-focusable `span` with `aria-disabled`.
- The free-shipping bar is a labelled `role="progressbar"`; the line list is a
  `<ul>` with `aria-label` and `aria-busy` while a mutation is in flight.

### `src/components/cart/CartProvider.tsx`

Unchanged. The public `useCart()` API is identical; the opener/last-focused
element is tracked inside the drawer, so nothing else had to move.

### `src/components/cart/AddToCartButton.tsx`

`aria-busy` while the server action is pending, `aria-disabled` alongside the
real `disabled`, and an explicit `focus-visible` ring in the default class
string (the button is ink-on-ink, so it needs its own offset outline).

### `src/components/shop/Filters.tsx`

- Every filter group is a `<fieldset>` with a `<legend>`; the collapse control
  lives in the legend with `aria-expanded` and `aria-controls` pointing at the
  panel, which is toggled with `hidden` rather than being unmounted.
- Availability, gender and surface rows were already checkboxes; the input now
  precedes the styled box so the visual box can mirror focus through Tailwind
  `peer-focus-visible:` variants.
- Colour swatches and size chips were `aria-pressed` buttons; they are now real
  `<input type="checkbox">` controls behind visually hidden labels, so they
  participate in the group, expose checked state and are keyboard operable with
  Space. Colour swatches carry an sr-only name ("Green (12 products)") because
  the colour alone is not a text alternative.
- The price slider has a real `<label>` (sr-only) and `aria-valuetext` so the
  value is announced as a formatted price, not a bare number.

### `src/components/shop/Listing.tsx`

- The product grid is a `<ul>` / `<li>` list; each card is one list item.
- The page's single `<h1>` stays in `src/app/shop/[[...segments]]/page.tsx`; the
  listing adds an sr-only `<h2>` "Products" that labels the results `<section>`,
  and the sidebar `<h2>` "Filters" labels the sidebar.
- The results count is `role="status" aria-live="polite" aria-atomic="true"`, so
  changing a filter or sort announces "12 products".
- The sort `<select>` has a visible-to-AT `<label for>` instead of `aria-label`.
- Applied-filter chips are a labelled list; each remove button reads "Remove
  filter: Size M" (the chip text itself is `aria-hidden` so it is not doubled).
- The mobile Filters button has `aria-expanded` / `aria-controls`, and the
  bottom sheet is a modal dialog with the same treatment as the cart drawer:
  focus in, Tab trapped, Escape closes, focus returns to the Filters button,
  `inert` when closed.

### `src/components/product/ProductCard.tsx`

- One link per card. Previously the whole card was a `<Link>` with a `<button>`
  nested inside it (invalid HTML, two overlapping activations). Now the card is
  a positioned `<div>`, the product title link stretches over the card with an
  `::after` overlay, and the quick-add button sits above the overlay as an
  independent, second control.
- The link's accessible name is the product name. The card image is `alt=""`
  (decorative — the title is right there), so the product is announced once.
- Quick add reads "Quick add Ace Unisex Tee to bag".
- The price appears once. Colour dots are `aria-hidden` with an sr-only
  "4 colours available" summary.
- The focus ring is drawn on the stretched overlay, so keyboard focus outlines
  the whole card rather than one line of text.

### `src/components/product/ProductDetail.tsx`

- Variant picker is a radio group per option: `<fieldset>` + sr-only `<legend>`
  (the visible option heading is `aria-hidden` to avoid a double announcement),
  with visually hidden `<input type="radio">` inputs behind styled labels. One
  tab stop per option, arrow keys move between values, Space selects.
- **Sold-out values** are computed from the variant list and announced with an
  sr-only "(sold out)"; non-swatch chips also show it visually (struck through),
  swatches dim.
- A `role="status" aria-live="polite"` region announces the selected variant's
  price and availability whenever the selection changes.
- Gallery thumbnails are buttons in a labelled list, named "Show image 2 of 4:
  <alt text>", with `aria-pressed` / `aria-current` for the active one. The
  large hero image keeps the real alt text; thumbnails' inner images are
  `alt=""` because the button already carries the name.
- Accordions: `aria-expanded` + `aria-controls`, panels are
  `role="region" aria-labelledby` the button and are hidden with `hidden`, so
  the store-authored description HTML lives in a labelled, reachable region.
  Each accordion header is wrapped in an `<h2>` under the page `<h1>`.
- "Add to bag" gets `aria-busy`, `aria-disabled`, and `aria-describedby`
  pointing at the "choose a size" error (which is `role="alert"`).
- The struck-through compare-at price is prefixed with an sr-only "Was".

### `src/app/globals.css`

- `:focus-visible` keeps the 2px `--color-green-deep` outline (9.4:1 on paper,
  3.4:1 on `--color-surface`) and now adds a 2px paper-coloured halo in the
  outline gap, so the ring is still visible against ink-dark controls
  (Add to bag, Checkout, selected size chips).
- Explicit `.sr-only` definition mirroring Tailwind's utility, since several
  components depend on it for real form inputs.
- `[inert] { pointer-events: none; user-select: none }` as belt-and-braces for
  the background behind an open modal.
- The existing `prefers-reduced-motion: reduce` block already neutralises every
  transition touched in this pass (drawer slide, sheet slide, chevron rotation,
  card zoom).

---

## WCAG 2.2 AA criteria addressed

| Criterion | Where |
| --- | --- |
| 1.1.1 Non-text Content (A) | Decorative images `alt=""`, icon SVGs `aria-hidden`, colour swatches given sr-only names |
| 1.3.1 Info and Relationships (A) | fieldset/legend filter and variant groups, `<ul>`/`<li>` product grid and chip list, heading order h1 → h2 |
| 1.3.5 Identify Input Purpose (AA) | Native checkbox/radio/select/range inputs instead of `aria-pressed` buttons |
| 1.4.11 Non-text Contrast (AA) | Focus ring green-deep + paper halo; selected-state rings |
| 2.1.1 Keyboard (A) | Every filter, swatch, size, thumbnail and quick-add is a native control |
| 2.1.2 No Keyboard Trap (A) | Drawer/sheet traps are modal-scoped and always released on close |
| 2.4.3 Focus Order (A) | Focus into the dialog on open, back to the opener on close |
| 2.4.4 Link Purpose (A) | One link per card, named by the product |
| 2.4.6 Headings and Labels (AA) | sr-only section headings, `<label for>` on sort and price |
| 2.4.7 Focus Visible (AA) | Global `:focus-visible`, `peer-focus-visible` on hidden inputs |
| 2.4.11 Focus Not Obscured (Minimum) (AA, 2.2) | `outline-offset` + halo keeps the ring clear of sticky edges; modals inert the background so focus cannot land behind the scrim |
| 2.5.3 Label in Name (A) | Visible chip/button text is contained in the accessible name |
| 2.5.8 Target Size (Minimum) (AA, 2.2) | Quantity 32px + spacing, size chips 44px min-width, close buttons 40px |
| 3.2.2 On Input (A) | No control changes context on focus; filters update the results list in place and announce it |
| 4.1.2 Name, Role, Value (A) | dialog/progressbar/status roles, `aria-expanded`, `aria-busy`, `aria-disabled` |
| 4.1.3 Status Messages (AA) | Bag status/error, results count, variant price/availability live regions |

---

## Still to do

**Owned by the header/nav/search agent this run** — they should ensure:

- A "Skip to main content" link as the first focusable element, targeting the
  `<main>` in `src/app/layout.tsx` (2.4.1 Bypass Blocks).
- Primary nav in a `<nav>` with an accessible name; dropdowns operable by
  keyboard, dismissible with Escape (1.4.13).
- The mobile menu treated as a modal dialog exactly like the cart drawer:
  `role="dialog"`, `aria-modal`, labelled, focus in, Tab trapped, Escape closes,
  focus returned to the hamburger, background `inert`, and `inert` on itself
  when closed (currently its links are still tab stops when off-canvas).
- The hamburger and search buttons need `aria-expanded` / `aria-controls`.
- The search dialog needs a labelled combobox, `aria-controls` on the listbox,
  `aria-activedescendant` for arrow-key navigation, a live region announcing
  result counts, and focus return to the search trigger on close.
- The bag button needs an accessible name that includes the count ("Bag,
  3 items") and should be the element focus returns to when the drawer closes
  (this side already handles the return, it just needs to stay focusable).
- Sticky header must not obscure a focused element scrolled to the top
  (2.4.11) — `scroll-margin-top` on focusable landmarks.

**Not covered anywhere yet:**

- Contrast audit of `--color-subtle` (#8c9286) on paper: 2.9:1, which fails
  1.4.3 for body text. It is currently used for secondary text ("Out of stock",
  "Secure checkout powered by Shopify", card meta). Needs a design decision —
  darkening to roughly #6b7266 gets it to 4.5:1.
- Product description HTML comes from Shopify; heading levels and image alt text
  inside it are the merchandiser's responsibility. Worth a content guideline.
- No automated axe run in CI.
- Zoom / reflow (1.4.10) at 320px and 400% has not been verified.
- Forms outside the shopping flow (newsletter, contact) were not in scope.

---

## Manual QA checklist

### Keyboard only (no mouse)

1. **Product card grid** (`/shop/tops`): Tab through the grid. Each card should
   take **two** stops at most — the product title link (ring around the whole
   card) and, where present, the quick-add button. Never a third stop for the
   image.
2. **Quick add**: focus a quick-add button and press Enter. The drawer opens and
   focus lands in it. Press Escape — focus returns to that same quick-add button.
3. **Sort**: Tab to the sort select, change it with arrow keys. A screen reader
   should announce the new product count.
4. **Filters (desktop)**: Tab into the sidebar. Each group header toggles with
   Enter/Space and reports expanded/collapsed. Checkboxes toggle with Space, and
   the styled box shows a focus ring. The price slider moves with arrow keys and
   announces a dollar value.
5. **Filters (mobile, ≤1024px)**: activate "Filters". Focus moves into the
   sheet, Tab cycles inside it only, Escape closes it and focus returns to the
   Filters button.
6. **Filter chips**: after applying filters, Tab to a chip and press Enter — the
   filter is removed and the count is announced.
7. **PDP** (`/product/ace-unisex`): Tab order should be thumbnails → (size guide)
   → each option group (one stop per group; arrow keys change the value) →
   Add to bag → the four accordion headers. Selecting a size should announce the
   price and availability.
8. **Sold-out variants**: pick a product with a sold-out size; the chip is struck
   through and announces "(sold out)".
9. **Cart drawer**: from the PDP press Enter on Add to bag. Focus moves into the
   drawer. Tab: close → −/quantity/+ per line → Remove per line → Checkout, then
   wraps. Shift+Tab wraps backwards. Nothing behind the scrim is reachable.
10. **Drawer close paths**: Escape, the close button, and "Continue shopping"
    each return focus to the control that opened the drawer.
11. **Quantity**: change a quantity; the live region should announce the new item
    count and subtotal once (not per keystroke).

### Screen reader spot checks (VoiceOver + Safari, NVDA + Firefox)

- Drawer opens announced as "Your Bag, dialog".
- Filter groups announced as "Colour, group" with "checkbox, not checked".
- Variant options announced as "Size, group … Medium, radio button, 2 of 5".
- Product cards read once: name, price, "4 colours available".

### Visual

- Focus ring is visible on every control, including the ink-dark Add to bag and
  Checkout buttons and the selected (black) size chip.
- Browser zoom to 200%: no clipped focus rings, no horizontal scroll.
- macOS "Reduce motion" on: drawer and sheet appear without sliding.
- Windows High Contrast / forced-colors: selected filters and variants are still
  distinguishable (they rely on `ring`/background, so verify).
