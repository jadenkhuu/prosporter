import "server-only";

/**
 * Cart operations that could not go through `index.ts` (CLNT-171).
 *
 * `queries.CART_DISCOUNT_CODES_UPDATE` declares `$discountCodes: [String!]`
 * while `cartDiscountCodesUpdate(discountCodes:)` is `[String!]!` on API
 * 2026-07, so the Storefront API rejects every call with
 * "Nullability mismatch on variable $discountCodes". `index.ts` / `queries.ts`
 * are owned elsewhere, so the corrected mutation lives here until that variable
 * declaration is fixed upstream — then delete this file and go back to
 * `updateCartDiscountCodes` from `index.ts`.
 */
import { shopifyFetch } from "./client";
import { CART_FRAGMENTS } from "./fragments";
import { CartUserError } from "./index";
import type { Cart, UserError } from "./types";

const CART_DISCOUNT_CODES_UPDATE_FIXED = /* GraphQL */ `
  ${CART_FRAGMENTS}
  mutation CartDiscountCodesUpdateFixed($cartId: ID!, $discountCodes: [String!]!) {
    cartDiscountCodesUpdate(cartId: $cartId, discountCodes: $discountCodes) {
      cart { ...Cart }
      userErrors { field message code }
    }
  }
`;

export async function updateCartDiscountCodesFixed(
  cartId: string,
  discountCodes: string[],
): Promise<Cart> {
  const data = await shopifyFetch<{
    cartDiscountCodesUpdate: { cart: Cart | null; userErrors: UserError[] };
  }>({
    query: CART_DISCOUNT_CODES_UPDATE_FIXED,
    variables: { cartId, discountCodes },
  });
  const payload = data.cartDiscountCodesUpdate;
  if (!payload) throw new Error("Missing cartDiscountCodesUpdate payload");
  if (payload.userErrors?.length) throw new CartUserError(payload.userErrors);
  if (!payload.cart) throw new Error("cartDiscountCodesUpdate returned no cart");
  return payload.cart;
}
