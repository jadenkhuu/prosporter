/** Public surface of the GA4 slice (CLNT-179). See ./track.ts and ./items.ts. */
export { CHECKOUT_LINKER_DOMAINS, isAnalyticsEnabled, isDebugEnabled, measurementId } from "./config";
export { nextPageView, pageViewPath } from "./page-view";
export { track, trackPageView } from "./track";
export type { AnalyticsEvent } from "./track";
export {
  addToCartParams,
  beginCheckoutParams,
  cartLineItem,
  findLineByVariant,
  itemsValue,
  productItem,
  round2,
  shortVariantId,
  viewItemParams,
} from "./items";
export type { AnalyticsItem, AnalyticsProduct, EcommerceParams } from "./items";
