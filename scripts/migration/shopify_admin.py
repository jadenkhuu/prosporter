#!/usr/bin/env python3
"""Shopify Admin API access for the migration pipeline.

The migration app is a Dev Dashboard app installed on the client's store, so
there is no long-lived pasted token. Access tokens are minted on demand with the
OAuth *client credentials* grant (POST /admin/oauth/access_token), last 24
hours, and are cached under exports/ (git-ignored) so repeated CLI runs reuse
one token instead of minting a new one every time.

Environment (.env.local, never committed):
  SHOPIFY_STORE_DOMAIN         prosporter.myshopify.com
  SHOPIFY_ADMIN_CLIENT_ID      Dev Dashboard app -> Settings -> Client ID
  SHOPIFY_ADMIN_CLIENT_SECRET  Dev Dashboard app -> Settings -> Client secret
  SHOPIFY_ADMIN_TOKEN          optional override: a pre-minted shpat_ token

Python 3 standard library only. Nothing here logs a secret; tokens are only
ever written to the cache file with mode 0600.

CLI:
  python3 scripts/migration/shopify_admin.py doctor   # scopes, locations, publications
  python3 scripts/migration/shopify_admin.py token    # refresh the cached token (prints expiry only)
  python3 scripts/migration/shopify_admin.py publish --handle nago --publication "ProSporter Dev" --activate
  python3 scripts/migration/shopify_admin.py publish --collection accessories --publication "ProSporter Dev"
                                                      # QA helpers: expose one product / collection to a Headless storefront
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from common import MIGRATION_OUT, ROOT, SHOPIFY_API_VERSION

TOKEN_CACHE = MIGRATION_OUT / ".admin-token.json"
REFRESH_MARGIN_SECONDS = 300  # mint a fresh token when < 5 minutes remain
THROTTLE_RETRIES = 5

# The scopes the pipeline needs. ``doctor`` fails when any are missing so a
# scope regression on the app is caught before a load starts.
REQUIRED_SCOPES = {
    "write_products",
    "write_inventory",
    "read_locations",
    "write_customers",
    "write_discounts",
    "write_content",
    "write_files",
    "write_publications",
    "write_metaobject_definitions",
    "read_markets",
}


class ShopifyAdminError(RuntimeError):
    """Configuration, transport or GraphQL failure. Message never carries a secret."""


def load_env(path: Path = ROOT / ".env.local") -> dict:
    """Parse KEY=value lines; process environment wins over the file."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in os.environ.items():
        if key.startswith("SHOPIFY_"):
            env[key] = value
    return env


def store_domain(env: dict) -> str:
    domain = env.get("SHOPIFY_STORE_DOMAIN", "").strip().lower()
    if not domain.endswith(".myshopify.com") or "/" in domain:
        raise ShopifyAdminError(
            "SHOPIFY_STORE_DOMAIN must be the store's *.myshopify.com domain"
        )
    return domain


def _read_cache() -> dict | None:
    try:
        data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "access_token" not in data:
        return None
    return data


def _write_cache(data: dict) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(TOKEN_CACHE, 0o600)


def mint_token(env: dict) -> dict:
    """Client-credentials grant. Returns {access_token, expires_at, scope, store}."""
    domain = store_domain(env)
    client_id = env.get("SHOPIFY_ADMIN_CLIENT_ID", "").strip()
    client_secret = env.get("SHOPIFY_ADMIN_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ShopifyAdminError(
            "SHOPIFY_ADMIN_CLIENT_ID and SHOPIFY_ADMIN_CLIENT_SECRET are required "
            "(Dev Dashboard -> app -> Settings) unless SHOPIFY_ADMIN_TOKEN is set"
        )
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    request = urllib.request.Request(
        f"https://{domain}/admin/oauth/access_token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ShopifyAdminError(
            f"token request rejected: HTTP {exc.code} (check client id/secret and that the "
            f"app is installed on {domain})"
        ) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ShopifyAdminError(f"token request failed: {exc.reason if hasattr(exc, 'reason') else exc}") from None
    token = payload.get("access_token")
    if not token:
        raise ShopifyAdminError("token response had no access_token")
    expires_in = int(payload.get("expires_in") or 86399)
    record = {
        "store": domain,
        "access_token": token,
        "expires_at": int(time.time()) + expires_in,
        "scope": sorted((payload.get("scope") or "").split(",")),
        "minted_at": int(time.time()),
    }
    _write_cache(record)
    return record


def get_token(env: dict | None = None, force: bool = False) -> str:
    """Cached client-credentials token, refreshed when near expiry.

    ``SHOPIFY_ADMIN_TOKEN`` (if set) short-circuits everything; it exists so a
    token minted elsewhere can be tested, not as the normal path.
    """
    env = env if env is not None else load_env()
    override = env.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if override:
        return override
    domain = store_domain(env)
    if not force:
        cached = _read_cache()
        if (
            cached
            and cached.get("store") == domain
            and cached.get("expires_at", 0) - time.time() > REFRESH_MARGIN_SECONDS
        ):
            return cached["access_token"]
    return mint_token(env)["access_token"]


class AdminClient:
    """Thin Admin GraphQL client with token refresh and throttle back-off."""

    def __init__(self, env: dict | None = None, api_version: str = SHOPIFY_API_VERSION):
        self.env = env if env is not None else load_env()
        self.domain = store_domain(self.env)
        self.endpoint = f"https://{self.domain}/admin/api/{api_version}/graphql.json"
        self.calls = 0

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """Return the ``data`` object. Raises ShopifyAdminError on any error."""
        attempt = 0
        refreshed = False
        while True:
            token = get_token(self.env)
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-Shopify-Access-Token": token,
                },
            )
            self.calls += 1
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and not refreshed and not self.env.get("SHOPIFY_ADMIN_TOKEN"):
                    refreshed = True
                    get_token(self.env, force=True)
                    continue
                if exc.code in (429, 502, 503, 504) and attempt < THROTTLE_RETRIES:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise ShopifyAdminError(f"Admin API HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt < THROTTLE_RETRIES:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise ShopifyAdminError("Admin API unreachable") from None

            errors = payload.get("errors") or []
            throttled = any(
                (err.get("extensions") or {}).get("code") == "THROTTLED" for err in errors
            )
            if throttled and attempt < THROTTLE_RETRIES:
                attempt += 1
                cost = (payload.get("extensions") or {}).get("cost") or {}
                status = cost.get("throttleStatus") or {}
                restore = float(status.get("restoreRate") or 50)
                needed = float(cost.get("requestedQueryCost") or 100)
                time.sleep(min(max(needed / restore, 1.0), 20))
                continue
            if errors:
                messages = "; ".join(str(err.get("message", "")) for err in errors)[:500]
                raise ShopifyAdminError(f"Admin API GraphQL error: {messages}")
            return payload.get("data") or {}

    def mutate(self, query: str, variables: dict, result_key: str) -> dict:
        """Run a mutation and raise on ``userErrors``."""
        data = self.graphql(query, variables)
        result = data.get(result_key) or {}
        user_errors = result.get("userErrors") or []
        if user_errors:
            messages = "; ".join(
                f"{'.'.join(map(str, e.get('field') or []))}: {e.get('message')}" for e in user_errors
            )[:500]
            raise ShopifyAdminError(f"{result_key} userErrors: {messages}")
        return result


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

DOCTOR_QUERY = """
{
  shop { name myshopifyDomain currencyCode primaryDomain { host } plan { publicDisplayName } }
  currentAppInstallation { accessScopes { handle } }
  locations(first: 10) { nodes { id name isActive fulfillsOnlineOrders } }
  publications(first: 20) { nodes { id name catalog { title } } }
  metafieldDefinitions(first: 50, ownerType: PRODUCT) { nodes { namespace key type { name } } }
  productsCount { count }
  collectionsCount { count }
  customersCount { count }
}
"""


def doctor(env: dict | None = None) -> dict:
    """Connectivity + scope report. Returns a JSON-serialisable summary, raises on failure."""
    client = AdminClient(env)
    data = client.graphql(DOCTOR_QUERY)
    granted = {s["handle"] for s in (data.get("currentAppInstallation") or {}).get("accessScopes", [])}
    missing = sorted(REQUIRED_SCOPES - granted)
    shop = data.get("shop") or {}
    summary = {
        "store": shop.get("myshopifyDomain"),
        "shop_name": shop.get("name"),
        "currency": shop.get("currencyCode"),
        "primary_domain": (shop.get("primaryDomain") or {}).get("host"),
        "plan": (shop.get("plan") or {}).get("publicDisplayName"),
        "api_version": SHOPIFY_API_VERSION,
        "scopes_granted": sorted(granted),
        "scopes_missing": missing,
        "locations": [
            {"id": n["id"], "name": n["name"], "active": n["isActive"], "online": n["fulfillsOnlineOrders"]}
            for n in (data.get("locations") or {}).get("nodes", [])
        ],
        "publications": [
            {"id": n["id"], "name": n["name"]}
            for n in (data.get("publications") or {}).get("nodes", [])
        ],
        "product_metafield_definitions": [
            f"{n['namespace']}.{n['key']} ({n['type']['name']})"
            for n in (data.get("metafieldDefinitions") or {}).get("nodes", [])
        ],
        "counts": {
            "products": (data.get("productsCount") or {}).get("count"),
            "collections": (data.get("collectionsCount") or {}).get("count"),
            "customers": (data.get("customersCount") or {}).get("count"),
        },
    }
    if missing:
        raise ShopifyAdminError(
            "app is missing required scopes: " + ", ".join(missing)
            + "\n" + json.dumps(summary, indent=2)
        )
    return summary


def publish_product(handle: str, publication_name: str, activate: bool, env: dict | None = None,
                    kind: str = "product") -> dict:
    """Publish one product or collection to a named publication (the Headless
    storefront); ``activate`` also sets a product ACTIVE. This is a QA step
    outside the pipeline: the load itself never publishes, so this is the only
    place a product changes status. Storefront API indexing lags ~1 minute."""
    client = AdminClient(env)
    if kind == "collection":
        data = client.graphql(
            "query($h:String!){ collectionByIdentifier(identifier:{handle:$h}){ id }"
            " publications(first:20){ nodes{ id name } } }", {"h": handle},
        )
        node = data.get("collectionByIdentifier")
    else:
        data = client.graphql(
            "query($h:String!){ productByIdentifier(identifier:{handle:$h}){ id status }"
            " publications(first:20){ nodes{ id name } } }", {"h": handle},
        )
        node = data.get("productByIdentifier")
    if not node:
        raise ShopifyAdminError(f"no {kind} with handle {handle!r}")
    publication = next((n for n in data["publications"]["nodes"] if n["name"] == publication_name), None)
    if not publication:
        names = [n["name"] for n in data["publications"]["nodes"]]
        raise ShopifyAdminError(f"no publication named {publication_name!r}; have {names}")
    if kind == "product" and activate and node["status"] != "ACTIVE":
        client.mutate(
            "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id } userErrors{ field message } } }",
            {"p": {"id": node["id"], "status": "ACTIVE"}}, "productUpdate",
        )
    client.mutate(
        "mutation($id:ID!,$i:[PublicationInput!]!){ publishablePublish(id:$id, input:$i){"
        " publishable{ availablePublicationsCount{ count } } userErrors{ field message } } }",
        {"id": node["id"], "i": [{"publicationId": publication["id"]}]}, "publishablePublish",
    )
    return {"kind": kind, "handle": handle, "id": node["id"], "publication": publication["name"],
            **({"status": "ACTIVE" if activate else node["status"]} if kind == "product" else {})}


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "doctor"
    try:
        if command == "doctor":
            print(json.dumps(doctor(), indent=2))
            return 0
        if command == "publish":
            import argparse
            parser = argparse.ArgumentParser(prog="shopify_admin.py publish")
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument("--handle", help="product handle")
            group.add_argument("--collection", help="collection handle")
            parser.add_argument("--publication", default="ProSporter Dev")
            parser.add_argument("--activate", action="store_true", help="also set the product ACTIVE")
            args = parser.parse_args(argv[2:])
            if args.collection:
                out = publish_product(args.collection, args.publication, False, kind="collection")
            else:
                out = publish_product(args.handle, args.publication, args.activate)
            print(json.dumps(out, indent=2))
            return 0
        if command == "token":
            record = mint_token(load_env())
            remaining = record["expires_at"] - int(time.time())
            print(json.dumps({
                "store": record["store"],
                "expires_in_seconds": remaining,
                "scopes": record["scope"],
                "cache": str(TOKEN_CACHE.relative_to(ROOT)),
            }, indent=2))
            return 0
        print(__doc__)
        return 2
    except ShopifyAdminError as exc:
        print(f"shopify_admin: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
