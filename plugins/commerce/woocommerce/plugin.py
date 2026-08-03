from __future__ import annotations

import base64
import html
import json
import re
import ssl
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from src.core.content import Entity

PLUGIN_ID = "commerce.woocommerce"
API_PATH = "/wp-json/wc/v3"
ALLOWED_READ_METHODS = {"GET"}
BLOCKED_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class WooCommerceError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class SecretReader(Protocol):
    def get_secret(self, secret_reference: str) -> str: ...


@dataclass(frozen=True)
class WooCommerceConfig:
    store_url: str
    consumer_key_secret_ref: str
    consumer_secret_secret_ref: str
    timeout: float = 10.0
    page_size: int = 25
    verify_tls: bool = True
    store_id: str = ""
    currency: str = "EUR"
    max_pages: int = 10

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WooCommerceConfig:
        config = cls(
            store_url=str(payload.get("store_url") or ""),
            consumer_key_secret_ref=str(payload.get("consumer_key_secret_ref") or ""),
            consumer_secret_secret_ref=str(payload.get("consumer_secret_secret_ref") or ""),
            timeout=float(payload.get("timeout", 10.0)),
            page_size=int(payload.get("page_size", 25)),
            verify_tls=bool(payload.get("verify_tls", True)),
            store_id=str(payload.get("store_id") or ""),
            currency=str(payload.get("currency") or "EUR").upper(),
            max_pages=int(payload.get("max_pages", 10)),
        )
        return config.validate()

    def validate(self) -> WooCommerceConfig:
        normalized = normalize_store_url(self.store_url)
        if not self.consumer_key_secret_ref.startswith("secretref:"):
            raise WooCommerceError("config.consumer_key_secret_ref_required", "Consumer key must use a secret ref.")
        if not self.consumer_secret_secret_ref.startswith("secretref:"):
            raise WooCommerceError(
                "config.consumer_secret_secret_ref_required",
                "Consumer secret must use a secret ref.",
            )
        if self.timeout <= 0 or self.timeout > 60:
            raise WooCommerceError("config.invalid_timeout", "Timeout must be between 0 and 60 seconds.")
        if self.page_size <= 0 or self.page_size > 100:
            raise WooCommerceError("config.invalid_page_size", "Page size must be between 1 and 100.")
        if self.max_pages <= 0 or self.max_pages > 100:
            raise WooCommerceError("config.invalid_max_pages", "Max pages must be between 1 and 100.")
        store_id = self.store_id or stable_store_id(normalized)
        return replace(self, store_url=normalized, store_id=store_id)

    def redacted(self) -> dict[str, Any]:
        return {
            "store_url": self.store_url,
            "consumer_key_secret_ref": redact_secret_ref(self.consumer_key_secret_ref),
            "consumer_secret_secret_ref": redact_secret_ref(self.consumer_secret_secret_ref),
            "timeout": self.timeout,
            "page_size": self.page_size,
            "verify_tls": self.verify_tls,
            "store_id": self.store_id,
            "currency": self.currency,
            "max_pages": self.max_pages,
        }


@dataclass(frozen=True)
class WooCommerceVariant:
    variant_id: str
    attributes: dict[str, str]
    price: float | None
    regular_price: float | None
    sale_price: float | None
    stock_status: str
    stock_quantity: int | None = None
    image: dict[str, Any] | None = None


@dataclass(frozen=True)
class WooCommerceProduct:
    product_id: str
    title: str
    description: str
    images: tuple[dict[str, Any], ...]
    price: float | None
    currency: str
    availability: str
    variants: tuple[dict[str, Any], ...]
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    product_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


class StaticSecretReader:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get_secret(self, secret_reference: str) -> str:
        if secret_reference not in self.values:
            raise WooCommerceError("secret.missing", "Configured WooCommerce secret is unavailable.")
        return self.values[secret_reference]


class WooCommerceHttpClient:
    def __init__(self, *, config: WooCommerceConfig, secret_reader: SecretReader) -> None:
        self.config = config.validate()
        self.secret_reader = secret_reader

    def get_json(self, path: str, query: dict[str, Any] | None = None) -> Any:
        return self._request_json("GET", path, query=query)

    def request_mutation(self, method: str, path: str) -> None:
        raise WooCommerceError("http.mutation_blocked", f"{method.upper()} is not allowed for read-only catalog.")

    def _request_json(self, method: str, path: str, query: dict[str, Any] | None = None) -> Any:
        method = method.upper()
        if method not in ALLOWED_READ_METHODS:
            raise WooCommerceError("http.mutation_blocked", f"{method} is not allowed for read-only catalog.")
        url = self._url(path, query=query or {})
        headers = {
            "Accept": "application/json",
            "User-Agent": "SocialMediaManager-WooCommerce-ReadOnly/0.1",
            "Authorization": self._authorization_header(),
        }
        context = None if self.config.verify_tls else ssl._create_unverified_context()  # noqa: S323
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.config.timeout, context=context) as response:  # noqa: S310
                raw = response.read()
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except TimeoutError as exc:
            raise WooCommerceError("timeout", "WooCommerce request timed out.") from exc
        except URLError as exc:
            raise WooCommerceError("store_unreachable", "WooCommerce store is unreachable.") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WooCommerceError("provider_output_invalid", "WooCommerce returned invalid JSON.") from exc

    def _url(self, path: str, query: dict[str, Any]) -> str:
        if not path.startswith("/"):
            path = "/" + path
        if ".." in path or path.startswith("//"):
            raise WooCommerceError("url.invalid_path", "WooCommerce API path is invalid.")
        base = self.config.store_url.rstrip("/")
        api_url = urljoin(base + "/", API_PATH.strip("/") + path)
        parsed = urlparse(api_url)
        if parsed.netloc != urlparse(base).netloc:
            raise WooCommerceError("url.host_override_blocked", "Per-request host override is blocked.")
        clean_query = "&".join(
            f"{key}={value}" for key, value in sorted(query.items()) if value is not None and str(value) != ""
        )
        return urlunparse(parsed._replace(query=clean_query))

    def _authorization_header(self) -> str:
        consumer_key = self.secret_reader.get_secret(self.config.consumer_key_secret_ref)
        consumer_secret = self.secret_reader.get_secret(self.config.consumer_secret_secret_ref)
        token = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode("ascii")
        return f"Basic {token}"

    @staticmethod
    def _http_error(exc: HTTPError) -> WooCommerceError:
        if exc.code in {401, 403}:
            return WooCommerceError("authentication_failed", "WooCommerce authentication failed.")
        if exc.code == 404:
            return WooCommerceError("api_unavailable", "WooCommerce API endpoint is unavailable.")
        if exc.code == 429:
            return WooCommerceError("rate_limited", "WooCommerce API rate limited the request.")
        if 500 <= exc.code <= 599:
            return WooCommerceError("provider_error", "WooCommerce provider returned a server error.")
        return WooCommerceError("http_error", "WooCommerce request failed.", {"status": exc.code})


class WooCommerceCatalogPlugin:
    capabilities = (
        "entity.product",
        "commerce.product_catalog",
        "commerce.product_lookup",
        "commerce.product_media",
        "outcome.product_click",
        "outcome.sale",
    )

    def __init__(
        self,
        *,
        config: WooCommerceConfig | dict[str, Any] | None = None,
        secret_reader: SecretReader | None = None,
        http_client: WooCommerceHttpClient | None = None,
    ) -> None:
        self.config = (
            config
            if isinstance(config, WooCommerceConfig)
            else WooCommerceConfig.from_dict(config or default_config_payload())
        )
        self.secret_reader = secret_reader or StaticSecretReader()
        self.client = http_client or WooCommerceHttpClient(config=self.config, secret_reader=self.secret_reader)
        self._products: tuple[WooCommerceProduct, ...] = ()
        self._sync: dict[str, Any] = {
            "status": "not_synced",
            "last_sync_at": "",
            "product_count": 0,
            "store_id": self.config.store_id,
        }
        self._source_missing: set[str] = set()

    def health_check(self) -> dict[str, Any]:
        configured = bool(
            self.config.store_url and self.config.consumer_key_secret_ref and self.config.consumer_secret_secret_ref
        )
        return {
            "status": "ready" if configured else "not_configured",
            "plugin_id": PLUGIN_ID,
            "store": self.config.store_url,
            "store_id": self.config.store_id,
            "catalog_status": self._sync["status"],
            "product_count": self._sync["product_count"],
            "last_sync_at": self._sync["last_sync_at"],
            "capabilities": list(self.capabilities),
            "read_only": True,
            "payment_mutation": False,
            "order_creation": False,
            "mutation_methods": [],
            "config": self.config.redacted(),
        }

    def test_connection(self) -> dict[str, Any]:
        try:
            payload = self.client.get_json("/products", {"per_page": 1, "page": 1})
        except WooCommerceError as exc:
            return {"status": exc.code, "message": exc.message, "store": self.config.store_url}
        if not isinstance(payload, list):
            return {"status": "provider_output_invalid", "message": "WooCommerce products response is invalid."}
        return {"status": "ready", "store": self.config.store_url, "read_only": True}

    def sync_products(self) -> dict[str, Any]:
        self._sync = dict(self._sync) | {"status": "running"}
        started = now_iso()
        staged: list[WooCommerceProduct] = []
        pages_fetched = 0
        try:
            for page in range(1, self.config.max_pages + 1):
                payload = self.client.get_json("/products", {"per_page": self.config.page_size, "page": page})
                if not isinstance(payload, list):
                    raise WooCommerceError("provider_output_invalid", "WooCommerce products page is invalid.")
                if not payload:
                    break
                pages_fetched += 1
                for item in payload:
                    if not isinstance(item, dict):
                        raise WooCommerceError("provider_output_invalid", "WooCommerce product payload is invalid.")
                    variations = self._variations_for(item)
                    staged.append(map_product(item, config=self.config, variations=variations))
                if len(payload) < self.config.page_size:
                    break
        except WooCommerceError as exc:
            self._sync = {
                "status": "failed",
                "last_sync_at": self._sync.get("last_sync_at", ""),
                "product_count": len(self._products),
                "store_id": self.config.store_id,
                "error_code": exc.code,
                "message": exc.message,
                "pages_fetched": pages_fetched,
            }
            return dict(self._sync)
        previous_ids = {product.product_id for product in self._products}
        new_ids = {product.product_id for product in staged}
        self._source_missing = previous_ids - new_ids
        self._products = tuple(staged)
        completed = now_iso()
        self._sync = {
            "status": "succeeded",
            "last_sync_at": completed,
            "product_count": len(self._products),
            "store_id": self.config.store_id,
            "started_at": started,
            "pages_fetched": pages_fetched,
            "source_missing": sorted(self._source_missing),
        }
        return dict(self._sync)

    def list_products(self, *, include_unavailable: bool = True) -> list[WooCommerceProduct]:
        if include_unavailable:
            return list(self._products)
        return [product for product in self._products if product.availability == "in_stock"]

    def lookup(self, product_id: str) -> WooCommerceProduct | None:
        return next((product for product in self._products if product.product_id == product_id), None)

    def search(self, query: str, *, include_unavailable: bool = True) -> list[WooCommerceProduct]:
        terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if term}
        scored: list[tuple[int, str, WooCommerceProduct]] = []
        for product in self.list_products(include_unavailable=include_unavailable):
            haystack = " ".join(
                [
                    product.title,
                    product.description,
                    " ".join(product.categories),
                    " ".join(product.tags),
                    str(product.metadata.get("sku", "")),
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, product.title, product))
        return [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))]

    def product_entities(self) -> list[Entity]:
        return [
            Entity(
                id=f"entity.product.{product.product_id}",
                entity_type="product",
                source_plugin=PLUGIN_ID,
                external_ref=product.metadata["woocommerce"]["external_ref"],
                title=product.title,
                metadata=asdict(product)
                | {
                    "trust_boundary": "external_untrusted_commerce_data",
                    "catalog_sync": self._sync,
                    "source_missing": product.product_id in self._source_missing,
                },
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
            "read_only": True,
        }

    def commercial_cta_context(self, product: WooCommerceProduct) -> dict[str, Any]:
        context = {
            "title": product.title,
            "product_url": product.product_url,
            "availability": product.availability,
            "no_discount_claim": product.metadata.get("sale_price") is None,
        }
        if product.price is not None:
            context["price"] = product.price
            context["currency"] = product.currency
        return context

    def _variations_for(self, item: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        if str(item.get("type") or "") != "variable":
            return ()
        product_id = item.get("id")
        if product_id is None:
            return ()
        payload = self.client.get_json(f"/products/{product_id}/variations", {"per_page": 100, "page": 1})
        if not isinstance(payload, list):
            raise WooCommerceError("provider_output_invalid", "WooCommerce variations payload is invalid.")
        return tuple(item for item in payload if isinstance(item, dict))


def default_config_payload() -> dict[str, Any]:
    return {
        "store_url": "https://woocommerce.example.invalid",
        "consumer_key_secret_ref": "secretref:woocommerce/consumer-key",
        "consumer_secret_secret_ref": "secretref:woocommerce/consumer-secret",
        "timeout": 10,
        "page_size": 25,
        "verify_tls": True,
        "currency": "EUR",
    }


def normalize_store_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise WooCommerceError("url.invalid_scheme", "WooCommerce store URL must be http or https.")
    if parsed.username or parsed.password:
        raise WooCommerceError("url.credentials_embedded", "Credentials are not allowed in the store URL.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise WooCommerceError("url.insecure_http", "HTTP store URLs are allowed only for local development fixtures.")
    if not parsed.netloc:
        raise WooCommerceError("url.host_required", "WooCommerce store URL requires a host.")
    return urlunparse(parsed._replace(path="", params="", query="", fragment="")).rstrip("/")


def stable_store_id(store_url: str) -> str:
    parsed = urlparse(store_url)
    host = re.sub(r"[^a-z0-9]+", "-", (parsed.netloc or "store").lower()).strip("-")
    return host or "store"


def map_product(
    payload: dict[str, Any], *, config: WooCommerceConfig, variations: tuple[dict[str, Any], ...] = ()
) -> WooCommerceProduct:
    external_id = payload.get("id")
    if external_id is None:
        raise WooCommerceError("provider_output_invalid", "WooCommerce product id is required.")
    title = plain_text(str(payload.get("name") or ""))
    if not title:
        raise WooCommerceError("provider_output_invalid", "WooCommerce product title is required.")
    description = canonical_description(payload)
    price, price_status = parse_price(payload.get("price"))
    regular_price, _ = parse_price(payload.get("regular_price"))
    sale_price, _ = parse_price(payload.get("sale_price"))
    images = tuple(map_image(image, index) for index, image in enumerate(payload.get("images") or []))
    categories = tuple(plain_text(str(item.get("name") or "")) for item in payload.get("categories") or [])
    tags = tuple(plain_text(str(item.get("name") or "")) for item in payload.get("tags") or [])
    mapped_variants = tuple(asdict(map_variant(variation)) for variation in variations)
    product_id = f"woocommerce.{config.store_id}.{external_id}"
    return WooCommerceProduct(
        product_id=product_id,
        title=title,
        description=description,
        images=images,
        price=price,
        currency=config.currency,
        availability=map_availability(payload.get("stock_status")),
        variants=mapped_variants,
        tags=tags,
        categories=categories,
        product_url=str(payload.get("permalink") or ""),
        metadata={
            "source_plugin": PLUGIN_ID,
            "short_description": plain_text(str(payload.get("short_description") or "")),
            "regular_price": regular_price,
            "sale_price": sale_price,
            "price_status": price_status,
            "stock_status": str(payload.get("stock_status") or "unknown"),
            "stock_quantity": payload.get("stock_quantity"),
            "sku": str(payload.get("sku") or ""),
            "woocommerce": {
                "store_id": config.store_id,
                "product_id": external_id,
                "external_ref": f"woocommerce:{config.store_id}:{external_id}",
                "type": str(payload.get("type") or ""),
                "catalog_api": API_PATH,
            },
            "canonical_text": description,
            "trust_boundary": "external_untrusted_commerce_data",
        },
    )


def map_variant(payload: dict[str, Any]) -> WooCommerceVariant:
    price, _ = parse_price(payload.get("price"))
    regular_price, _ = parse_price(payload.get("regular_price"))
    sale_price, _ = parse_price(payload.get("sale_price"))
    attributes = {
        plain_text(str(item.get("name") or "")): plain_text(str(item.get("option") or ""))
        for item in payload.get("attributes") or []
        if isinstance(item, dict)
    }
    image = payload.get("image") if isinstance(payload.get("image"), dict) else None
    return WooCommerceVariant(
        variant_id=str(payload.get("id") or ""),
        attributes=attributes,
        price=price,
        regular_price=regular_price,
        sale_price=sale_price,
        stock_status=map_availability(payload.get("stock_status")),
        stock_quantity=payload.get("stock_quantity"),
        image=map_image(image, 0) if image else None,
    )


def parse_price(value: Any) -> tuple[float | None, str]:
    text = str(value if value is not None else "").strip()
    if text == "":
        return None, "unavailable"
    try:
        return float(text), "available"
    except ValueError:
        return None, "unavailable"


def map_availability(stock_status: Any) -> str:
    value = str(stock_status or "").lower()
    if value == "instock":
        return "in_stock"
    if value == "outofstock":
        return "out_of_stock"
    if value == "onbackorder":
        return "on_backorder"
    return "unknown"


def map_image(payload: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "url": str(payload.get("src") or ""),
        "alt": plain_text(str(payload.get("alt") or "")),
        "position": int(payload.get("position", index) or index),
        "external_id": str(payload.get("id") or ""),
    }


def canonical_description(payload: dict[str, Any]) -> str:
    pieces = [
        plain_text(str(payload.get("name") or "")),
        plain_text(str(payload.get("short_description") or "")),
        plain_text(str(payload.get("description") or "")),
        " ".join(plain_text(str(item.get("name") or "")) for item in payload.get("categories") or []),
        " ".join(plain_text(str(item.get("name") or "")) for item in payload.get("tags") or []),
    ]
    return " ".join(piece for piece in pieces if piece).strip()


def plain_text(value: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def redact_secret_ref(reference: str) -> str:
    if not reference:
        return ""
    suffix = reference.rsplit("/", maxsplit=1)[-1].rsplit(":", maxsplit=1)[-1]
    return f"secretref:***{suffix[-4:]}" if suffix else "secretref:***"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
