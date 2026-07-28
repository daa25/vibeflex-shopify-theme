from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    store: str
    token: str
    api_version: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BASE_DIR / ".env")
        return cls(
            store=os.getenv("SHOPIFY_STORE", "").strip().replace("https://", "").rstrip("/"),
            token=os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip(),
            api_version=os.getenv("SHOPIFY_API_VERSION", "2026-07").strip(),
            dry_run=os.getenv("DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "y"},
        )


class ShopifyError(RuntimeError):
    pass


class ShopifyClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = (
            f"https://{settings.store}/admin/api/{settings.api_version}/graphql.json"
        )

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.settings.token,
            },
            json={"query": query, "variables": variables},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise ShopifyError(json.dumps(payload["errors"], indent=2))
        return payload["data"]

    def create_product(self, item: dict[str, str], recipe: dict[str, Any]) -> dict[str, Any]:
        colors = recipe["colors"]
        sizes = recipe["sizes"]
        media = []
        if item.get("artwork_url"):
            media.append(
                {
                    "originalSource": item["artwork_url"],
                    "alt": f"{item['title']} artwork",
                    "mediaContentType": "IMAGE",
                }
            )

        mutation = """
        mutation CreateProduct($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
          productCreate(product: $product, media: $media) {
            product {
              id
              title
              status
              options {
                id
                name
                optionValues { id name }
              }
            }
            userErrors { field message }
          }
        }
        """
        variables = {
            "product": {
                "title": item["title"],
                "descriptionHtml": f"<p>{item['description']}</p>",
                "vendor": recipe["vendor"],
                "productType": recipe["product_type"],
                "status": "DRAFT",
                "tags": recipe.get("tags", []),
                "productOptions": [
                    {"name": "Color", "values": [{"name": value} for value in colors]},
                    {"name": "Size", "values": [{"name": value} for value in sizes]},
                ],
            },
            "media": media or None,
        }
        data = self.graphql(mutation, variables)["productCreate"]
        self._raise_user_errors(data.get("userErrors", []))
        return data["product"]

    def create_variants(
        self,
        product_id: str,
        item: dict[str, str],
        recipe: dict[str, Any],
    ) -> list[dict[str, Any]]:
        variants = []
        for color, size in product(recipe["colors"], recipe["sizes"]):
            sku = self._sku(item["design"], color, size)
            variants.append(
                {
                    "price": str(recipe["price"]),
                    "optionValues": [
                        {"optionName": "Color", "name": color},
                        {"optionName": "Size", "name": size},
                    ],
                    "inventoryItem": {"sku": sku, "tracked": False},
                }
            )

        mutation = """
        mutation CreateVariants($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkCreate(
            productId: $productId,
            variants: $variants,
            strategy: REMOVE_STANDALONE_VARIANT
          ) {
            productVariants {
              id
              title
              price
              sku
              selectedOptions { name value }
            }
            userErrors { field message }
          }
        }
        """
        data = self.graphql(
            mutation,
            {"productId": product_id, "variants": variants},
        )["productVariantsBulkCreate"]
        self._raise_user_errors(data.get("userErrors", []))
        return data["productVariants"]

    @staticmethod
    def _sku(design: str, color: str, size: str) -> str:
        clean = lambda value: "".join(ch for ch in value.upper() if ch.isalnum())
        return f"VF-{clean(design)}-{clean(color)[:4]}-{clean(size)}"

    @staticmethod
    def _raise_user_errors(errors: list[dict[str, Any]]) -> None:
        if errors:
            formatted = "; ".join(error.get("message", "Unknown Shopify error") for error in errors)
            raise ShopifyError(formatted)


def load_recipes() -> dict[str, Any]:
    with (BASE_DIR / "config" / "recipes.json").open(encoding="utf-8") as file:
        return json.load(file)


def load_products() -> list[dict[str, str]]:
    with (BASE_DIR / "data" / "products.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return [row for row in rows if row.get("enabled", "").strip().lower() in {"1", "true", "yes", "y"}]


def validate(settings: Settings, products: list[dict[str, str]], recipes: dict[str, Any]) -> None:
    if not products:
        raise ValueError("No enabled products were found in data/products.csv")
    for item in products:
        if item["recipe"] not in recipes:
            raise ValueError(f"Unknown recipe '{item['recipe']}' for {item['title']}")
    if not settings.dry_run:
        if not settings.store:
            raise ValueError("SHOPIFY_STORE is missing from .env")
        if not settings.token:
            raise ValueError("SHOPIFY_ADMIN_TOKEN is missing from .env")


def print_plan(products: list[dict[str, str]], recipes: dict[str, Any]) -> None:
    print("\nVibeFlex launch plan\n" + "=" * 40)
    total_variants = 0
    for item in products:
        recipe = recipes[item["recipe"]]
        count = len(recipe["colors"]) * len(recipe["sizes"])
        total_variants += count
        print(f"- {item['title']}: {count} variants at ${recipe['price']}")
    print(f"\nProducts: {len(products)}")
    print(f"Variants: {total_variants}\n")


def main() -> int:
    settings = Settings.from_env()
    recipes = load_recipes()
    products = load_products()
    validate(settings, products, recipes)
    print_plan(products, recipes)

    if settings.dry_run:
        print("DRY_RUN=true — preview complete. Nothing was sent to Shopify.")
        return 0

    client = ShopifyClient(settings)
    for item in products:
        recipe = recipes[item["recipe"]]
        print(f"Creating draft: {item['title']}...")
        created = client.create_product(item, recipe)
        variants = client.create_variants(created["id"], item, recipe)
        print(f"Created {created['title']} with {len(variants)} variants.")

    print("\nAll enabled launch products were created as Shopify drafts.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, ShopifyError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
