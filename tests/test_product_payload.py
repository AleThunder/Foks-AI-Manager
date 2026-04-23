from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_payload import BuildSavePayloadService
from app.infrastructure.db import SnapshotRepository, TaskRepository, configure_database, upgrade_database
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
  <input name="nameExt['prom']" value="Marketplace title" />
  <prod-features marketid="prom" catid="cat-1" custcatid="custom-1"></prod-features>
  <prod-markup-info :extinfo='{"prom":{"foo":"bar"}}'></prod-markup-info>
  <script>
    saveProduct('save', 'X-CSRF-TOKEN', 'csrf-123')
  </script>
</form>
"""


class FakeSession:
    """Serve deterministic HTML and JSON payloads for save-payload tests."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        """Store constructor inputs to mimic the real session signature."""
        self.base_url = base_url
        self.username = username
        self.password = password

    def get_html(self, path: str, params: dict[str, str] | None = None) -> str:
        """Return fixture HTML for search and product modal requests."""
        if path == "/c/products":
            return SEARCH_HTML
        if path == "/c/products/productModal":
            return MODAL_HTML
        raise AssertionError(path)

    def get_json(self, path: str, params: dict[str, str] | None = None):
        """Return fixture feature payloads keyed by integration endpoint."""
        if path.startswith("/api/v1/product/features/"):
            return {"Color": ["Black"]}
        if path == "/api/v1/market-cat/features":
            return [{"name": "Color", "facet": True}]
        raise AssertionError(path)

    def build_json_headers(self, csrf_token: str, referer_path: str = "/c/products") -> dict[str, str]:
        """Return headers in the same shape as the real FOKS session helper."""
        return {
            "X-CSRF-TOKEN": csrf_token,
            "Referer": f"{self.base_url}{referer_path}",
        }


class ProductPayloadTests(unittest.TestCase):
    """Verify save-payload building from normalized modal snapshots."""

    def setUp(self) -> None:
        """Point repository-backed services at an isolated SQLite database for the test run."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._database_url = f"sqlite:///{Path(self._temp_dir.name) / 'test.db'}"
        configure_database(url=self._database_url, force=True)
        upgrade_database(url=self._database_url)

    def tearDown(self) -> None:
        """Restore the default application database configuration after each test."""
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_build_save_payload_uses_normalized_modal_snapshot(self) -> None:
        """Payload building should preserve normalized fields, headers, and feature arrays."""
        service = BuildSavePayloadService(
            snapshot_repository=SnapshotRepository(),
            task_repository=TaskRepository(),
            session_factory=FakeSession,
        )

        result = service.build_save_payload(
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
            article="ART-777",
        )

        self.assertEqual(result["url"], "/c/products/save")
        self.assertEqual(result["headers"]["X-CSRF-TOKEN"], "csrf-123")
        self.assertEqual(result["payload"]["id"], "prod-1")
        self.assertEqual(result["payload"]["marketCatIds"]["prom"], "cat-1")
        self.assertEqual(result["payload"]["nameExt"]["prom"], "Marketplace title")
        self.assertEqual(result["payload"]["featureNames"]["prom"], ["Color"])
        self.assertEqual(result["payload"]["featureValues"]["prom"], ["Black"])


if __name__ == "__main__":
    unittest.main()
