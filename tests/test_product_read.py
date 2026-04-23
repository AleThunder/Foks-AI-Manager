from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_read import GetProductByArticleService
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
  <prod-features marketid="prom" catid="cat-1" custcatid="custom-1"></prod-features>
  <script>
    saveProduct('save', 'X-CSRF-TOKEN', 'csrf-123')
  </script>
</form>
"""


class FakeSession:
    """Serve deterministic search, modal, and feature payloads for read-flow tests."""

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
        """Return fixture JSON for product and category feature endpoints."""
        if path.startswith("/api/v1/product/features/"):
            return [
                {"name": "Color", "values": ["Black"]},
                {"name": "Memory", "value": "128 GB"},
            ]
        if path == "/api/v1/market-cat/features":
            return [
                {"name": "Color", "facet": True, "required": True, "options": ["Black", "White"]},
                {"name": "Memory", "facet": False, "values": ["64 GB", "128 GB"]},
            ]
        raise AssertionError(path)


class ProductReadTests(unittest.TestCase):
    """Cover the end-to-end product read orchestration against fake FOKS responses."""

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

    def test_get_product_by_article_returns_single_snapshot(self) -> None:
        """Reading by article should persist one normalized snapshot with marketplace features."""
        service = GetProductByArticleService(
            snapshot_repository=SnapshotRepository(),
            task_repository=TaskRepository(),
            session_factory=FakeSession,
        )

        snapshot = service.get_product_by_article(
            base_url="https://my.foks.biz",
            username="user",
            password="pass",
            article="ART-777",
        )

        self.assertEqual(snapshot.article, "ART-777")
        self.assertEqual(snapshot.pid, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        self.assertEqual(snapshot.product_id, "prod-1")
        self.assertEqual(snapshot.offer_id, "offer-1")
        self.assertIn("prom", snapshot.marketplaces)
        self.assertEqual(snapshot.marketplaces["prom"].market_cat_id, "cat-1")
        self.assertEqual(snapshot.marketplaces["prom"].market_id, "prom")
        self.assertEqual(len(snapshot.marketplaces["prom"].raw_product_features), 2)
        self.assertEqual(snapshot.marketplaces["prom"].current_features["Color"].values, ["Black"])
        self.assertEqual(snapshot.marketplaces["prom"].current_features["Memory"].values, ["128 GB"])
        self.assertTrue(snapshot.marketplaces["prom"].allowed_features["Color"].required)
        self.assertEqual(
            snapshot.marketplaces["prom"].allowed_features["Memory"].options,
            ["64 GB", "128 GB"],
        )


if __name__ == "__main__":
    unittest.main()
