/**
 * Site-wide promo strip. Deliberately a server component rendered by the root
 * layout rather than part of `Header`: it is static text, it is the first thing
 * painted, and on a product page it is the Largest Contentful Paint element
 * (QA defect D3). Keeping it outside the header's client boundary means its
 * markup ships in the RSC payload and never waits on the header's bundle.
 */
export function AnnouncementBar() {
  return (
    <div className="bg-ink text-paper">
      <div className="mx-auto flex max-w-[1400px] items-center justify-center px-4 py-2 text-center">
        <span className="eyebrow text-[10px] text-surface-2">
          EXAMPLE PROMOTIONAL TEXT || Free shipping on orders over $150 · Australia-wide
        </span>
      </div>
    </div>
  );
}
