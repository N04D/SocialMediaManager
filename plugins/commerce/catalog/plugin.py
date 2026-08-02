from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.core.content import Entity

PLUGIN_ID = "commerce.catalog"


@dataclass(frozen=True)
class Product:
    product_id: str
    title: str
    description: str
    images: tuple[str, ...]
    price: float
    currency: str
    availability: str
    variants: tuple[str, ...]
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    product_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


class CommerceCatalogPlugin:
    capabilities = (
        "entity.product",
        "commerce.product_catalog",
        "commerce.product_lookup",
        "commerce.product_media",
        "outcome.product_click",
        "outcome.sale",
    )

    def __init__(self) -> None:
        self._products = (
            Product(
                product_id="sabr-tshirt",
                title="Sabr T-shirt",
                description="A black cotton T-shirt with a restrained Sabr calligraphy design.",
                images=("fixture://catalog/sabr-tshirt-front.png", "fixture://catalog/sabr-tshirt-detail.png"),
                price=29.0,
                currency="EUR",
                availability="in_stock",
                variants=("S", "M", "L", "XL"),
                tags=("sabr", "patience", "calligraphy", "reflection"),
                categories=("apparel", "arabic_calligraphy"),
                product_url="https://shop.example.test/products/sabr-tshirt",
                metadata={"inventory_quantity": 42, "campaign_eligible": True},
            ),
            Product(
                product_id="sabr-hoodie",
                title="Sabr Hoodie",
                description="A warmer Sabr design for winter campaigns.",
                images=("fixture://catalog/sabr-hoodie.png",),
                price=59.0,
                currency="EUR",
                availability="out_of_stock",
                variants=("M", "L"),
                tags=("sabr", "patience", "hoodie"),
                categories=("apparel",),
                product_url="https://shop.example.test/products/sabr-hoodie",
                metadata={"inventory_quantity": 0, "campaign_eligible": False},
            ),
            Product(
                product_id="coffee-mug",
                title="Coffee mug",
                description="A simple ceramic mug for morning notes.",
                images=("fixture://catalog/coffee-mug.png",),
                price=14.0,
                currency="EUR",
                availability="in_stock",
                variants=("white",),
                tags=("coffee", "desk"),
                categories=("home",),
                product_url="https://shop.example.test/products/coffee-mug",
                metadata={"inventory_quantity": 18, "campaign_eligible": True},
            ),
            Product(
                product_id="generic-notebook",
                title="Generic notebook",
                description="Plain dotted notebook for planning.",
                images=("fixture://catalog/notebook.png",),
                price=9.0,
                currency="EUR",
                availability="in_stock",
                variants=("A5",),
                tags=("notebook", "planning"),
                categories=("stationery",),
                product_url="https://shop.example.test/products/notebook",
                metadata={"inventory_quantity": 100, "campaign_eligible": True},
            ),
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "plugin_id": PLUGIN_ID,
            "catalog_status": "fixture_read_only",
            "product_count": len(self._products),
            "payment_mutation": False,
            "order_creation": False,
        }

    def list_products(self, *, include_unavailable: bool = True) -> list[Product]:
        if include_unavailable:
            return list(self._products)
        return [product for product in self._products if product.availability == "in_stock"]

    def lookup(self, product_id: str) -> Product | None:
        return next((product for product in self._products if product.product_id == product_id), None)

    def product_entities(self) -> list[Entity]:
        return [
            Entity(
                id=f"entity.product.{product.product_id}",
                entity_type="product",
                source_plugin=PLUGIN_ID,
                external_ref=product.product_id,
                title=product.title,
                metadata=asdict(product),
            )
            for product in self._products
        ]

    def outcome_capabilities(self) -> tuple[str, ...]:
        return ("outcome.product_click", "outcome.sale")

    def promotion_policy(self) -> dict[str, Any]:
        return {
            "never_invent_discounts": True,
            "only_available_products": True,
            "external_publication_requires_confirmation": True,
            "payment_mutation": False,
            "order_creation": False,
        }
