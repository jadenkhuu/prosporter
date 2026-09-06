# Responsive layout and console errors (CLNT-179, Workstream 7)

- Target: `https://prosporter.vercel.app`
- Engine: Chrome/152.0.7977.76 driven over the Chrome DevTools Protocol by `scripts/qa/console-and-responsive.mjs` (no Playwright/Puppeteer in this repo; nothing was installed).
- Widths: 375, 768, 1280 px. Each measurement is a fresh tab and a fresh navigation, then 3000 ms of settle time for hydration.
- Generated 2026-09-06T02:28:37.624Z.

Acceptance criteria covered: section 1 criterion 1 (renders without horizontal scroll or broken layout at 375/768/1280) and criterion 9 (no JavaScript console errors on any key page).

## Summary

- Measurements: 27 (9 pages x 3 widths).
- Horizontal overflow: **1** of 27.
- Measurements with console or uncaught JS errors: **0** of 27.
- Screenshots: 27 PNGs in `screenshots/`, largest 384 KB.

## Horizontal overflow (`documentElement.scrollWidth > clientWidth`)

| Page | Path | 375 px | 768 px | 1280 px |
|---|---|---|---|---|
| home | `/` | ok (375) | ok (768) | ok (1280) |
| shop | `/shop` | ok (375) | ok (768) | ok (1280) |
| collection | `/shop/jerseys` | ok (375) | ok (768) | ok (1280) |
| product | `/product/ace-unisex` | **OVERFLOW** 648>375 | ok (768) | ok (1280) |
| search | `/search?q=jersey` | ok (375) | ok (768) | ok (1280) |
| blog | `/blog` | ok (375) | ok (768) | ok (1280) |
| article | `/blog/how-to-choose-the-right-sport-merchant-for-your-business` | ok (375) | ok (768) | ok (1280) |
| contact | `/contact` | ok (375) | ok (768) | ok (1280) |
| not-found | `/qa-404-check-clnt-179` | ok (375) | ok (768) | ok (1280) |

### Overflowing elements

| Page | Width | Element | Class | left | right |
|---|---:|---|---|---:|---:|
| product | 375 | `div` | `fixed inset-0 z-[90] lg:hidden pointer-events-none` | 0 | 648 |
| product | 375 | `div` | `absolute inset-0 bg-ink/50 transition-opacity opacity-0` | 0 | 648 |
| product | 375 | `div` | `absolute left-0 top-0 flex h-full w-[85%] max-w-sm flex-col bg-paper outline-non` | -384 | 0 |
| product | 375 | `div` | `flex items-center justify-between border-b border-line px-5 py-4` | -384 | 0 |
| product | 375 | `h2` | `display text-xl` | -364 | -301 |
| product | 375 | `button` | `-mr-2 grid h-10 w-10 place-items-center rounded-full hover:bg-surface` | -52 | -12 |
| product | 375 | `svg` | `` | -42 | -22 |
| product | 375 | `path` | `` | -37 | -27 |

## Product-page overflow sweep (375 px)

One product page is not enough evidence: the overflow scales with the number of gallery thumbnails. 30 product URLs (evenly sampled from the `crawl-results.csv` 200s) were measured at 375 px.

- Overflowing: **8 of 30** (27%).
- Document scroll widths seen: 465, 556, 648, 740, 833, 1200 px against a 375 px viewport.
- Widest in-flow element on each overflowing page:
  - `img.object-cover` on 8 pages

| Product URL | scrollWidth | Overflow | Widest in-flow element |
|---|---:|---|---|
| `/product/ace-unisex` | 648 | **yes** | `img.object-cover` (80 px) |
| `/product/baldo-hoodie` | 556 | **yes** | `img.object-cover` (80 px) |
| `/product/baldo-pants` | 465 | **yes** | `img.object-cover` (80 px) |
| `/product/beach-volley-bikini-bottoms-purple` | 375 | no | — |
| `/product/beach-volley-shorts-tijuana-green` | 375 | no | — |
| `/product/beach-volley-singlet-osaka-ocean` | 375 | no | — |
| `/product/beach-volley-womens-shorts-tijuana-black` | 375 | no | — |
| `/product/beach-volleyball-crop-top-ibiza-white` | 375 | no | — |
| `/product/beach-volleyball-crop-top-osaka-river` | 375 | no | — |
| `/product/carrum-womens-jersey-black-and-yellow` | 375 | no | — |
| `/product/elbow-pads` | 375 | no | — |
| `/product/inner-west-volley-mens-polo-shirt` | 375 | no | — |
| `/product/inner-west-volley-womens-old-style` | 375 | no | — |
| `/product/innerwest-volley-brione-pants-trousers` | 375 | no | — |
| `/product/jump-spin-socks-1-pairs-pack` | 375 | no | — |
| `/product/knee-pads-sleek` | 1200 | **yes** | `img.object-cover` (80 px) |
| `/product/modena-unisex-jacket` | 375 | no | — |
| `/product/nine-knee-pads-new-shield` | 556 | **yes** | `img.object-cover` (80 px) |
| `/product/ora` | 375 | no | — |
| `/product/ponale-pants` | 375 | no | — |
| `/product/prosporter-ball-cart-trolley-replacement-bag-inner-fabric` | 375 | no | — |
| `/product/provolley-brione-track-pants` | 375 | no | — |
| `/product/provolley-kids-training-shorts` | 375 | no | — |
| `/product/provolley-mens-volleyball-jersey-sydney` | 833 | **yes** | `img.object-cover` (80 px) |
| `/product/provolley-training-t-shirt` | 375 | no | — |
| `/product/provolley-women-shorts-navy-white-yellow` | 833 | **yes** | `img.object-cover` (80 px) |
| `/product/provolley-womens-volleyball-jersey-sydney-australia` | 740 | **yes** | `img.object-cover` (80 px) |
| `/product/sette-shirt` | 375 | no | — |
| `/product/tennessee-shirt` | 375 | no | — |
| `/product/val-male-t-shirt` | 375 | no | — |

## Console and JavaScript errors

`console.error` counts JavaScript-side errors only. Chrome's own network log entries (including the 404 route's intended status) are counted in the last column instead, because they are not JavaScript console errors and criterion 9 is about JavaScript.

| Page | Width | HTTP | Uncaught JS | console.error | Network >= 400 / failed |
|---|---:|---:|---:|---:|---:|
| home | 375 | 200 | 0 | 0 | 0 |
| home | 768 | 200 | 0 | 0 | 0 |
| home | 1280 | 200 | 0 | 0 | 0 |
| shop | 375 | 200 | 0 | 0 | 0 |
| shop | 768 | 200 | 0 | 0 | 0 |
| shop | 1280 | 200 | 0 | 0 | 0 |
| collection | 375 | 200 | 0 | 0 | 0 |
| collection | 768 | 200 | 0 | 0 | 0 |
| collection | 1280 | 200 | 0 | 0 | 0 |
| product | 375 | 200 | 0 | 0 | 0 |
| product | 768 | 200 | 0 | 0 | 0 |
| product | 1280 | 200 | 0 | 0 | 0 |
| search | 375 | 200 | 0 | 0 | 0 |
| search | 768 | 200 | 0 | 0 | 0 |
| search | 1280 | 200 | 0 | 0 | 0 |
| blog | 375 | 200 | 0 | 0 | 0 |
| blog | 768 | 200 | 0 | 0 | 0 |
| blog | 1280 | 200 | 0 | 0 | 0 |
| article | 375 | 200 | 0 | 0 | 0 |
| article | 768 | 200 | 0 | 0 | 0 |
| article | 1280 | 200 | 0 | 0 | 0 |
| contact | 375 | 200 | 0 | 0 | 0 |
| contact | 768 | 200 | 0 | 0 | 0 |
| contact | 1280 | 200 | 0 | 0 | 0 |
| not-found | 375 | 404 | 0 | 0 | 2 |
| not-found | 768 | 404 | 0 | 0 | 2 |
| not-found | 1280 | 404 | 0 | 0 | 2 |

### Detail

**not-found @ 375 px** (`/qa-404-check-clnt-179`)

- network: `404 https://prosporter.vercel.app/qa-404-check-clnt-179`
- network: `[network] Failed to load resource: the server responded with a status of 404 () (https://prosporter.vercel.app/qa-404-check-clnt-179)`

**not-found @ 768 px** (`/qa-404-check-clnt-179`)

- network: `404 https://prosporter.vercel.app/qa-404-check-clnt-179`
- network: `[network] Failed to load resource: the server responded with a status of 404 () (https://prosporter.vercel.app/qa-404-check-clnt-179)`

**not-found @ 1280 px** (`/qa-404-check-clnt-179`)

- network: `404 https://prosporter.vercel.app/qa-404-check-clnt-179`
- network: `[network] Failed to load resource: the server responded with a status of 404 () (https://prosporter.vercel.app/qa-404-check-clnt-179)`

## Headings and titles seen (semantic structure, criterion 6)

| Page | `<title>` | h1 count | First headings |
|---|---|---:|---|
| home | `ProSporter — Volleyball Teamwear & Apparel` | 1 | `H2 H2 H1 H3 H3 H3 H3 H3` |
| shop | `Shop All · ProSporter` | 1 | `H2 H2 H1 H2 H2 H3 H3 H3` |
| collection | `Jerseys · ProSporter` | 1 | `H2 H2 H1 H2 H2 H3 H3 H3` |
| product | `Ace Unisex - ProSporter Australia` | 1 | `H2 H2 H1 H2 H2 H2 H3 H3` |
| search | `Search: jersey · ProSporter` | 1 | `H2 H2 H1 H3 H3 H3 H3 H3` |
| blog | `Journal · ProSporter` | 1 | `H2 H2 H1 H2 H2 H2 H2 H2` |
| article | `How to Choose the Right Sport Merchant for Your Business - ProSporter Australia` | 1 | `H2 H2 H1 H2 H2 H2 H2 H3` |
| contact | `Contact - ProSporter Australia` | 1 | `H2 H2 H1 H4 H4 H6 H6 H6` |
| not-found | `Not found · ProSporter` | 1 | `H2 H2 H1 H3 H3 H3` |

## Screenshots

| Page | 375 px | 768 px | 1280 px |
|---|---|---|---|
| home | [375](screenshots/home-375.png) (297 KB) | [768](screenshots/home-768.png) (266 KB) | [1280](screenshots/home-1280.png) (371 KB) |
| shop | [375](screenshots/shop-375.png) (205 KB) | [768](screenshots/shop-768.png) (308 KB) | [1280](screenshots/shop-1280.png) (336 KB) |
| collection | [375](screenshots/collection-375.png) (226 KB) | [768](screenshots/collection-768.png) (264 KB) | [1280](screenshots/collection-1280.png) (270 KB) |
| product | [375](screenshots/product-375.png) (175 KB) | [768](screenshots/product-768.png) (252 KB) | [1280](screenshots/product-1280.png) (231 KB) |
| search | [375](screenshots/search-375.png) (368 KB) | [768](screenshots/search-768.png) (384 KB) | [1280](screenshots/search-1280.png) (307 KB) |
| blog | [375](screenshots/blog-375.png) (252 KB) | [768](screenshots/blog-768.png) (261 KB) | [1280](screenshots/blog-1280.png) (310 KB) |
| article | [375](screenshots/article-375.png) (292 KB) | [768](screenshots/article-768.png) (326 KB) | [1280](screenshots/article-1280.png) (342 KB) |
| contact | [375](screenshots/contact-375.png) (127 KB) | [768](screenshots/contact-768.png) (150 KB) | [1280](screenshots/contact-1280.png) (159 KB) |
| not-found | [375](screenshots/not-found-375.png) (75 KB) | [768](screenshots/not-found-768.png) (81 KB) | [1280](screenshots/not-found-1280.png) (86 KB) |

