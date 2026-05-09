from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.dependencies import (
    get_payload_service,
    get_preview_patch_service,
    get_product_aggregate_service,
    get_product_refresh_service,
    get_save_patch_service,
)
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.application.services.product_payload import PrepareSavePayloadService
from app.application.services.product_preview import PreviewProductPatchService
from app.application.services.product_save import ApplyProductPatchService, SaveProductPatchService
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
    """Serve deterministic FOKS responses for API-level integration tests."""

    latest_title = "Old title"
    latest_color = "Black"
    post_count = 0

    def __init__(self, base_url: str, username: str, password: str) -> None:
        """Store constructor inputs to mimic the real session signature."""
        self.base_url = base_url
        self.username = username
        self.password = password

    def get_html(self, path: str, params: dict[str, str] | None = None) -> str:
        """Return fixture HTML for product search and modal requests."""
        if path == "/c/products":
            return SEARCH_HTML
        if path == "/c/products/productModal":
            return MODAL_HTML.replace('value="100" />', f'value="100" />\n  <input name="nameExt[\'prom\']" value="{self.latest_title}" />')
        raise AssertionError(path)

    def get_json(self, path: str, params: dict[str, str] | None = None):
        """Return fixture JSON for marketplace feature endpoints."""
        if path.startswith("/api/v1/product/features/"):
            return [
                {"name": "Color", "values": [self.latest_color]},
            ]
        if path == "/api/v1/market-cat/features":
            return [
                {"name": "Color", "facet": True, "required": True, "options": ["Black", "White"]},
            ]
        raise AssertionError(path)

    def build_json_headers(self, csrf_token: str, referer_path: str = "/c/products") -> dict[str, str]:
        """Return headers in the same shape as the real FOKS session helper."""
        return {
            "X-CSRF-TOKEN": csrf_token,
            "Referer": f"{self.base_url}{referer_path}",
        }

    def post_json(self, path: str, json_body: dict[str, object], csrf_token: str):
        """Capture saved values so the following refresh reflects the last successful save."""
        FakeSession.post_count += 1
        FakeSession.latest_title = str(json_body["nameExt"]["prom"])
        FakeSession.latest_color = str(json_body["featureValues"]["prom"][0])
        return {"ok": True, "saved": True}


class FakePatchGenerator:
    """Return a canned preview draft for API integration tests."""

    def generate_patch(self, *, context: dict[str, object], instructions: str) -> dict[str, object]:
        """Return a deterministic normalized patch payload."""
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
    """Exercise the public products API against fake FOKS and AI collaborators."""

    def setUp(self) -> None:
        """Boot the FastAPI app against an isolated SQLite database and fake dependencies."""
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
        refresh_service = RefreshProductAggregateService(
            snapshot_repository=snapshot_repository,
            task_repository=TaskRepository(),
            aggregate_repository=aggregate_repository,
            session_factory=FakeSession,
        )

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
        app.dependency_overrides[get_payload_service] = lambda: PrepareSavePayloadService(
            aggregate_service=aggregate_service,
            snapshot_repository=snapshot_repository,
            patch_repository=patch_repository,
            task_repository=TaskRepository(),
            apply_patch_service=ApplyProductPatchService(),
            session_factory=FakeSession,
        )
        app.dependency_overrides[get_save_patch_service] = lambda: SaveProductPatchService(
            aggregate_service=aggregate_service,
            refresh_service=refresh_service,
            snapshot_repository=snapshot_repository,
            patch_repository=patch_repository,
            task_repository=TaskRepository(),
            apply_patch_service=ApplyProductPatchService(),
            session_factory=FakeSession,
        )

        self._app = app
        self._client = TestClient(app)

    def tearDown(self) -> None:
        """Release the API client and restore the default database configuration."""
        self._client.close()
        self._app.dependency_overrides.clear()
        FakeSession.latest_title = "Old title"
        FakeSession.latest_color = "Black"
        FakeSession.post_count = 0

        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_refresh_and_read_endpoints_return_latest_persisted_aggregate(self) -> None:
        """Refresh and read endpoints should expose the same persisted aggregate state."""
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
        """Reading by article should return 404 for unknown persisted products."""
        response = self._client.get("/products/by-article", params={"article": "MISSING"})

        self.assertEqual(response.status_code, 404)

    def test_preview_patch_returns_persisted_draft(self) -> None:
        """Preview generation should return one persisted normalized draft envelope."""
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
                "created_by": "content.user",
                "instructions": "Improve Prom content.",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["created_by"], "content.user")
        self.assertEqual(payload["patch"]["marketplace_patches"]["prom"]["fields"]["nameExt"], "Preview title")
        self.assertEqual(payload["diff_summary"]["change_count"], 2)

    def test_patch_changes_endpoint_returns_compact_diff(self) -> None:
        """Patch changes endpoint should expose old and new values by marketplace field key."""
        self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )
        preview_response = self._client.post(
            "/products/preview-patch",
            json={
                "article": "ART-777",
                "created_by": "content.user",
                "instructions": "Improve Prom content.",
            },
        )
        patch_id = preview_response.json()["data"]["patch_id"]

        response = self._client.get(f"/products/patches/{patch_id}/changes")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["changes"]["prom[nameExt]"],
            ["Old title", "Preview title"],
        )
        self.assertEqual(
            response.json()["data"]["changes"]["prom[feature:Color]"],
            [["Black"], ["White"]],
        )

    def test_save_endpoint_approves_and_saves_persisted_draft(self) -> None:
        """Saving through the public API should approve the draft and verify the refreshed result."""
        self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )
        preview_response = self._client.post(
            "/products/preview-patch",
            json={
                "article": "ART-777",
                "created_by": "content.user",
                "instructions": "Improve Prom content.",
            },
        )
        patch_id = preview_response.json()["data"]["patch_id"]

        response = self._client.post(
            "/products/save",
            json={
                "patch_id": patch_id,
                "approved_by": "qa.user",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["status"], "saved")
        self.assertEqual(payload["created_by"], "content.user")
        self.assertEqual(payload["approved_by"], "qa.user")
        self.assertEqual(payload["save_result"]["audit"]["created_by"], "content.user")
        self.assertEqual(payload["save_result"]["audit"]["approved_by"], "qa.user")
        self.assertEqual(payload["save_result"]["verification"]["status"], "ok")

    def test_save_payload_prepares_final_payload_without_posting_to_foks(self) -> None:
        """Save-payload should prepare the final persisted save request without live-reading FOKS."""
        self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )
        preview_response = self._client.post(
            "/products/preview-patch",
            json={
                "article": "ART-777",
                "created_by": "content.user",
                "instructions": "Improve Prom content.",
            },
        )
        patch_id = preview_response.json()["data"]["patch_id"]

        response = self._client.post(
            "/products/save-payload",
            json={
                "patch_id": patch_id,
                "approved_by": "qa.user",
                "base_url": "https://my.foks.biz",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["patch"]["status"], "approved")
        self.assertEqual(payload["patch"]["approved_by"], "qa.user")
        self.assertEqual(payload["save_request"]["url"], "/c/products/save")
        self.assertEqual(payload["save_request"]["payload"]["nameExt"]["prom"], "Preview title")
        self.assertEqual(payload["save_request"]["payload"]["featureValues"]["prom"], ["White"])
        self.assertEqual(FakeSession.post_count, 0)

        save_response = self._client.post(
            "/products/save",
            json={
                "patch_id": patch_id,
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["data"]["status"], "saved")
        self.assertEqual(FakeSession.post_count, 1)

    def test_save_payload_rejects_legacy_article_contract(self) -> None:
        """Save-payload should reject the old article-based live-read request shape."""
        self._client.post(
            "/products/refresh",
            json={
                "article": "ART-777",
                "base_url": "https://my.foks.biz",
                "username": "user",
                "password": "pass",
            },
        )
        preview_response = self._client.post(
            "/products/preview-patch",
            json={
                "article": "ART-777",
                "created_by": "content.user",
                "instructions": "Improve Prom content.",
            },
        )
        patch_id = preview_response.json()["data"]["patch_id"]

        response = self._client.post(
            "/products/save-payload",
            json={
                "patch_id": patch_id,
                "article": "ART-777",
                "payload_only": True,
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
