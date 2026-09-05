#!/usr/bin/env python3
"""Idempotently register the storefront's Shopify webhook subscriptions.

The Next.js storefront never touches the Admin API, so subscriptions are managed
here, from the same Dev Dashboard app ("ProSporter-migration") the migration
pipeline uses. That app's *client secret* is also the HMAC signing key for every
webhook it registers, so the value in ``SHOPIFY_ADMIN_CLIENT_SECRET`` is what
the host must expose to the app as ``SHOPIFY_WEBHOOK_SECRET``. See
``docs/webhooks.md``.

Verified against the live Admin GraphQL schema at API version 2026-07:

  mutation ($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
    webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) { ... }
  }

  WebhookSubscriptionInput fields: format, includeFields, filter,
  metafieldNamespaces, metafields, name, uri
  -> the destination field is ``uri`` (a String). The older ``callbackUrl``
     field and the ``WebhookSubscriptionEndpoint`` union are gone in 2026-07.

Python 3 standard library only. Never prints a secret.

CLI:
  python3 scripts/webhooks/register_webhooks.py list
  python3 scripts/webhooks/register_webhooks.py ensure https://www.prosporter.co.uk
  python3 scripts/webhooks/register_webhooks.py ensure https://... --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MIGRATION_DIR = SCRIPT_DIR.parent / "migration"
if str(MIGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(MIGRATION_DIR))

from common import SHOPIFY_API_VERSION  # noqa: E402
from shopify_admin import AdminClient, ShopifyAdminError, load_env  # noqa: E402

WEBHOOK_PATH = "/api/webhooks/shopify"
FORMAT = "JSON"

# Topics the receiver in src/app/api/webhooks/shopify/route.ts acts on.
# INVENTORY_ITEMS_UPDATE is handled by the route but not registered by default:
# INVENTORY_LEVELS_UPDATE already covers stock movement and the items topic is
# noisy (it fires on cost/SKU edits too). Add it with --with-inventory-items.
MANAGED_TOPICS = [
    "PRODUCTS_CREATE",
    "PRODUCTS_UPDATE",
    "PRODUCTS_DELETE",
    "COLLECTIONS_CREATE",
    "COLLECTIONS_UPDATE",
    "COLLECTIONS_DELETE",
    "INVENTORY_LEVELS_UPDATE",
]
OPTIONAL_TOPICS = ["INVENTORY_ITEMS_UPDATE"]

LIST_QUERY = """
query WebhookSubscriptions($after: String) {
  webhookSubscriptions(first: 100, after: $after) {
    nodes { id topic uri format apiVersion { handle } includeFields createdAt updatedAt }
    pageInfo { hasNextPage endCursor }
  }
}
"""

CREATE_MUTATION = """
mutation CreateWebhook($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri format apiVersion { handle } }
    userErrors { field message }
  }
}
"""

UPDATE_MUTATION = """
mutation UpdateWebhook($id: ID!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionUpdate(id: $id, webhookSubscription: $sub) {
    webhookSubscription { id topic uri format apiVersion { handle } }
    userErrors { field message }
  }
}
"""

DELETE_MUTATION = """
mutation DeleteWebhook($id: ID!) {
  webhookSubscriptionDelete(id: $id) {
    deletedWebhookSubscriptionId
    userErrors { field message }
  }
}
"""


def endpoint_uri(base_url: str) -> str:
    """Normalise BASE_URL into the full https callback URI."""
    base = base_url.strip().rstrip("/")
    if not base:
        raise SystemExit("BASE_URL is required, e.g. https://www.prosporter.co.uk")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"BASE_URL must be an absolute http(s) URL, got {base!r}")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise SystemExit("Shopify only delivers to https endpoints (localhost excepted for tunnels)")
    if parsed.path.rstrip("/"):
        raise SystemExit(f"BASE_URL must be an origin without a path, got {base!r}")
    return f"{parsed.scheme}://{parsed.netloc}{WEBHOOK_PATH}"


def fetch_subscriptions(client: AdminClient) -> list[dict]:
    nodes: list[dict] = []
    after = None
    while True:
        data = client.graphql(LIST_QUERY, {"after": after})
        page = data.get("webhookSubscriptions") or {}
        nodes.extend(page.get("nodes") or [])
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return nodes
        after = info.get("endCursor")


def build_plan(existing: list[dict], topics: list[str], uri: str, prune: bool) -> list[dict]:
    """Return an ordered list of {action, topic, id, reason} steps."""
    by_topic: dict[str, list[dict]] = {}
    for node in existing:
        by_topic.setdefault(node.get("topic", ""), []).append(node)

    plan: list[dict] = []
    for topic in topics:
        matches = sorted(by_topic.get(topic, []), key=lambda n: n.get("createdAt") or "")
        if not matches:
            plan.append({"action": "create", "topic": topic, "id": None, "uri": uri,
                         "reason": "no subscription for this topic"})
            continue
        primary = matches[0]
        if primary.get("uri") != uri or primary.get("format") != FORMAT:
            plan.append({"action": "update", "topic": topic, "id": primary["id"], "uri": uri,
                         "reason": f"uri={primary.get('uri')!r} format={primary.get('format')!r}"})
        else:
            plan.append({"action": "ok", "topic": topic, "id": primary["id"], "uri": uri,
                         "reason": f"already correct (apiVersion {api_version_handle(primary)})"})
        for duplicate in matches[1:]:
            plan.append({
                "action": "delete" if prune else "duplicate",
                "topic": topic,
                "id": duplicate["id"],
                "uri": duplicate.get("uri"),
                "reason": "extra subscription for a managed topic"
                          + ("" if prune else " (pass --prune to remove)"),
            })

    managed = set(topics)
    for node in existing:
        if node.get("topic") not in managed:
            plan.append({"action": "leave", "topic": node.get("topic"), "id": node["id"],
                         "uri": node.get("uri"), "reason": "not managed by this script"})
    return plan


def apply_step(client: AdminClient, step: dict) -> dict:
    action = step["action"]
    sub = {"uri": step["uri"], "format": FORMAT}
    if action == "create":
        return client.mutate(CREATE_MUTATION, {"topic": step["topic"], "sub": sub},
                             "webhookSubscriptionCreate")
    if action == "update":
        return client.mutate(UPDATE_MUTATION, {"id": step["id"], "sub": sub},
                             "webhookSubscriptionUpdate")
    if action == "delete":
        return client.mutate(DELETE_MUTATION, {"id": step["id"]}, "webhookSubscriptionDelete")
    raise ShopifyAdminError(f"not a writable action: {action}")


def api_version_handle(node: dict) -> str:
    return ((node.get("apiVersion") or {}).get("handle")) or "?"


def short_id(gid: str | None) -> str:
    return (gid or "").rsplit("/", 1)[-1] or "-"


def cmd_list(client: AdminClient, as_json: bool) -> int:
    nodes = fetch_subscriptions(client)
    if as_json:
        print(json.dumps(nodes, indent=2))
        return 0
    print(f"{len(nodes)} webhook subscription(s) on {client.domain} (Admin {SHOPIFY_API_VERSION}):")
    for node in sorted(nodes, key=lambda n: (n.get("topic") or "")):
        print(f"  {node.get('topic'):<28} {node.get('format'):<5} v{api_version_handle(node)} "
              f"id={short_id(node.get('id'))}")
        print(f"      uri: {node.get('uri')}")
    return 0


def cmd_ensure(client: AdminClient, args: argparse.Namespace) -> int:
    uri = endpoint_uri(args.base_url)
    topics = list(MANAGED_TOPICS) + (OPTIONAL_TOPICS if args.with_inventory_items else [])
    existing = fetch_subscriptions(client)
    plan = build_plan(existing, topics, uri, args.prune)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] store={client.domain} api={SHOPIFY_API_VERSION}")
    print(f"[{mode}] endpoint={uri} format={FORMAT}")
    writable = [s for s in plan if s["action"] in ("create", "update", "delete")]
    for step in plan:
        print(f"  {step['action'].upper():<9} {step['topic']:<28} id={short_id(step['id'])}  {step['reason']}")
    print(f"[{mode}] {len(writable)} write(s) planned, {len(plan) - len(writable)} no-op(s)")

    if not args.apply:
        if writable:
            print("[DRY RUN] re-run with --apply to write these subscriptions")
        return 0

    failures = 0
    for step in writable:
        try:
            result = apply_step(client, step)
            created = result.get("webhookSubscription") or {}
            print(f"  done {step['action']} {step['topic']} -> id={short_id(created.get('id') or step['id'])}")
        except ShopifyAdminError as exc:
            failures += 1
            print(f"  FAIL {step['action']} {step['topic']}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="show every webhook subscription on the store")
    p_list.add_argument("--json", action="store_true", help="raw JSON instead of a table")

    p_ensure = sub.add_parser("ensure", help="create/update the storefront subscriptions")
    p_ensure.add_argument("base_url", help="storefront origin, e.g. https://www.prosporter.co.uk")
    p_ensure.add_argument("--apply", action="store_true",
                          help="write to the store (default is a dry run)")
    p_ensure.add_argument("--prune", action="store_true",
                          help="delete extra subscriptions on managed topics")
    p_ensure.add_argument("--with-inventory-items", action="store_true",
                          help="also register INVENTORY_ITEMS_UPDATE")

    args = parser.parse_args(argv)
    try:
        client = AdminClient(load_env())
        if args.command == "list":
            return cmd_list(client, args.json)
        return cmd_ensure(client, args)
    except ShopifyAdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
