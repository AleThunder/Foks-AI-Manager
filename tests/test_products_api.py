from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.dependencies import get_preview_patch_service, get_product_aggregate_service, get_product_refresh_service
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.application.services.product_preview import PreviewProductPatchService
from app.infrastructure.db import PatchRepository, ProductAggregateRepository, ProductRepository, SnapshotRepository, TaskRepository, configure_database, upgrade_database
from app.infrastructure.settings import get_settings


SEARCH_HTML = """
<div class="product">
  <a href="/c/products/productModal?pid=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">Target item</a>
  <span>ART-777</span>
</div>
"""

MODAL_HTML = """
<form id="productForm">
  <input name="id" value="prod-1" />
  <input name="offerId" value="offer-1" />
  <input name="name" value="Demo product" />
  <input name="marketCatIds['prom']" value="cat-1" />
  <input name="marketCatNames['prom']" value="Category 1" />
  <input name="priceExt['prom']" value="100" />
  <prod-features marketid="prom" catid="cat-1" custcatid="custom-1"></prod-features>
  <script>
    saveProduct('save', 'X-CSRF-TOKEN', 'csrf-123')
  </script>
</form>
"""


class FakeSession:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password

    def get_html(self, path: str, params: dict[str, str] | None = None) -> str:
        if path == "/c/products":
            return SEARCH_HTML
        if path == "/c/products/productModal":
            return MODAL_HTML
        raise AssertionError(path)

    def get_json(self, path: str, params: dict[str, str] | None = None):
        if path.startswith("/api/v1/product/features/"):
            return [
                {"name": "Color", "values": ["Black"]},
            ]
        if path == "/api/v1/market-cat/features":
            return [
                {"name": "Color", "facet": True, "required": True, "options": ["Black", "White"]},
            ]
        raise AssertionError(path)


class FakePatchGenerator:
    def generate_patch(self, *, context: dict[str, object], instructions: str) -> dict[str, object]:
        return {
            "product_id": "prod-1",
            "offer_id": "offer-1",
            "marketplace_patches": [
                {
                    "market_id": "prom",
                    "fields": {"nameExt": "Preview title"},
                    "feature_values": [{"name": "Color", "values": ["White"]}],
                }
            ],
        }


class ProductsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._database_url = f"sqlite:///{Path(self._temp_dir.name) / 'test.db'}"
        configure_database(url=self._database_url, force=True)
        upgrade_database(url=self._database_url)

        product_repository = ProductRepository()
        snapshot_repository = SnapshotRepository(product_repository=product_repository)
        patch_repository = PatchRepository()
        aggregate_repository = ProductAggregateRepository(
            product_repository=product_repository,
            snapshot_repository=snapshot_repository,
        )
        aggregate_service = GetProductAggregateService(aggregate_repository=aggregate_repository)

        app = create_app()
        app.router.on_startup.clear()
        app.dependency_overrides[get_product_refresh_service] = lambda: RefreshProductAggregateService(
            snapshot_repository=snapshot_repository,
            task_repository=TaskRepository(),
            aggregate_repository=aggregate_repository,
            session_factory=FakeSession,
        )
        app.dependency_overrides[get_product_aggregate_service] = lambda: aggregate_service
        app.dependency_overrides[get_preview_patch_service] = lambda: PreviewProductPatchService(
            aggregate_service=aggregate_service,
            patch_repository=patch_repository,
            task_repository=TaskRepository(),
            patch_generator=FakePatchGenerator(),
        )

        self._app = app
        self._client = TestClient(app)

    def tearDown(self) -> None:
        self._client.close()
        self._app.dependency_overrides.clear()

        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_refresh_and_read_endpoints_return_latest_persisted_aggregate(self) -> None:
        refresh_response = self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )

        self.assertEqual(refresh_response.status_code, 200)
        refresh_payload = refresh_response.json()["data"]
        self.assertEqual(refresh_payload["identity"]["article"], "ART-777")
        self.assertEqual(refresh_payload["latest_snapshot"]["product_id"], "prod-1")
        self.assertEqual(refresh_payload["marketplaces"]["prom"]["market_cat_id"], "cat-1")
        self.assertEqual(
            refresh_payload["marketplaces"]["prom"]["current_features"]["Color"]["values"],
            ["Black"],
        )

        product_id = refresh_payload["identity"]["id"]
        by_article_response = self._client.get("/products/by-article", params={"article": "ART-777"})
        self.assertEqual(by_article_response.status_code, 200)
        self.assertEqual(by_article_response.json()["data"]["identity"]["id"], product_id)

        by_id_response = self._client.get(f"/products/{product_id}")
        self.assertEqual(by_id_response.status_code, 200)
        self.assertEqual(
            by_id_response.json()["data"]["latest_snapshot"]["id"],
            refresh_payload["latest_snapshot"]["id"],
        )

    def test_get_by_article_returns_404_when_product_is_missing(self) -> None:
        response = self._client.get("/products/by-article", params={"article": "MISSING"})

        self.assertEqual(response.status_code, 404)

    def test_preview_patch_returns_persisted_draft(self) -> None:
        self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )

        response = self._client.post(
            "/products/preview-patch",
            json={
                "article": "ART-777",
                "instructions": "Improve Prom content.",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["patch"]["marketplace_patches"]["prom"]["fields"]["nameExt"], "Preview title")
        self.assertEqual(payload["diff_summary"]["change_count"], 2)


if __name__ == "__main__":
    unittest.main()
