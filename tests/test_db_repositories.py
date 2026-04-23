from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.domain.models import FeatureValue, MarketplaceMeta, MarketplacePatch, MarketplaceSnapshot, ProductPatch, ProductSnapshot
from app.infrastructure.db import (
    PatchRepository,
    ProductAggregateRepository,
    ProductRepository,
    SnapshotRepository,
    TaskRepository,
    configure_database,
    upgrade_database,
)
from app.infrastructure.settings import get_settings


class DatabaseRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self._temp_dir.name) / "test.db"
        configure_database(
            url=f"sqlite:///{database_path}",
            force=True,
        )
        upgrade_database(url=f"sqlite:///{database_path}")

    def tearDown(self) -> None:
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_snapshot_repository_persists_and_reloads_domain_snapshot(self) -> None:
        repository = SnapshotRepository()
        snapshot = ProductSnapshot(
            article="ART-777",
            pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            product_id="prod-1",
            offer_id="offer-1",
            csrf_save_token="csrf-123",
            basic_fields={"name": "Demo"},
            flags={"published": True},
            marketplaces={
                "prom": MarketplaceSnapshot(
                    market_id="prom",
                    meta=MarketplaceMeta(marketid="prom", catid="cat-1", custcatid="cust-1"),
                    market_cat_id="cat-1",
                    market_cat_name="Category 1",
                    fields={"priceExt": "100"},
                    current_features={
                        "Color": FeatureValue(name="Color", values=["Black"], raw={"name": "Color"}),
                    },
                    allowed_features={
                        "Color": FeatureValue(
                            name="Color",
                            facet=True,
                            required=True,
                            options=["Black", "White"],
                            raw={"name": "Color", "facet": True},
                        ),
                    },
                    raw_product_features=[{"name": "Color", "values": ["Black"]}],
                    raw_category_features=[{"name": "Color", "facet": True}],
                    extinfo={"foo": "bar"},
                )
            },
        )

        product_record_id, persisted_snapshot = repository.save_snapshot(
            snapshot,
            raw_modal_html="<form>demo</form>",
        )

        self.assertGreater(product_record_id, 0)
        self.assertEqual(persisted_snapshot.article, "ART-777")
        self.assertEqual(persisted_snapshot.marketplaces["prom"].current_features["Color"].values, ["Black"])
        self.assertTrue(persisted_snapshot.marketplaces["prom"].allowed_features["Color"].required)
        self.assertEqual(ProductRepository().get_record_id_by_pid(persisted_snapshot.pid), product_record_id)

    def test_patch_repository_persists_patch_with_marketplace_payload(self) -> None:
        snapshot_repository = SnapshotRepository()
        patch_repository = PatchRepository()
        task_repository = TaskRepository()

        _, persisted_snapshot = snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-123",
                marketplaces={},
            )
        )
        product_record_id = snapshot_repository.get_product_record_id_by_pid(persisted_snapshot.pid)
        task_record_id = task_repository.start_task(task_id="task-1", task_type="build_save_payload")

        patch_id = patch_repository.save_patch(
            product_record_id=product_record_id or 0,
            patch=ProductPatch(
                product_id="prod-1",
                offer_id="offer-1",
                marketplace_patches={
                    "prom": MarketplacePatch(
                        market_id="prom",
                        market_cat_id="cat-1",
                        fields={"priceExt": "100"},
                    )
                },
            ),
            article="ART-777",
            pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            save_url="/c/products/save",
            headers={"X-CSRF-TOKEN": "csrf-123"},
            payload={"id": "prod-1"},
            task_record_id=task_record_id,
        )

        self.assertGreater(patch_id, 0)
        persisted_patch = patch_repository.get_patch_by_id(patch_id)
        self.assertIsNotNone(persisted_patch)
        assert persisted_patch is not None
        self.assertEqual(persisted_patch.patch.offer_id, "offer-1")
        self.assertEqual(persisted_patch.status, "built")

    def test_product_aggregate_repository_returns_latest_persisted_state(self) -> None:
        product_repository = ProductRepository()
        snapshot_repository = SnapshotRepository(product_repository=product_repository)
        patch_repository = PatchRepository()
        aggregate_repository = ProductAggregateRepository(
            product_repository=product_repository,
            snapshot_repository=snapshot_repository,
        )

        _, persisted_snapshot = snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-123",
                basic_fields={"name": "Demo"},
                flags={"published": True},
                marketplaces={
                    "prom": MarketplaceSnapshot(
                        market_id="prom",
                        meta=MarketplaceMeta(marketid="prom", catid="cat-1", custcatid="cust-1"),
                        market_cat_id="cat-1",
                        market_cat_name="Category 1",
                        fields={"priceExt": "100"},
                        current_features={
                            "Color": FeatureValue(name="Color", values=["Black"]),
                        },
                        allowed_features={
                            "Color": FeatureValue(name="Color", options=["Black", "White"], required=True),
                        },
                        extinfo={"foo": "bar"},
                    )
                },
            )
        )
        product_record_id = product_repository.get_record_id_by_pid(persisted_snapshot.pid)
        patch_repository.save_patch(
            product_record_id=product_record_id or 0,
            patch=ProductPatch(
                product_id="prod-1",
                offer_id="offer-1",
                marketplace_patches={
                    "prom": MarketplacePatch(
                        market_id="prom",
                        market_cat_id="cat-1",
                        fields={"priceExt": "100"},
                    )
                },
            ),
            article="ART-777",
            pid=persisted_snapshot.pid,
            base_snapshot_id=1,
            status="draft",
            save_url="/c/products/save",
            headers={"X-CSRF-TOKEN": "csrf-123"},
            payload={"id": "prod-1"},
        )

        aggregate = aggregate_repository.get_latest_aggregate_by_article("ART-777")

        self.assertIsNotNone(aggregate)
        assert aggregate is not None
        self.assertEqual(aggregate.identity.article, "ART-777")
        self.assertEqual(aggregate.identity.pid, persisted_snapshot.pid)
        self.assertEqual(aggregate.latest_snapshot.product_id if aggregate.latest_snapshot else None, "prod-1")
        self.assertIn("prom", aggregate.marketplaces)
        self.assertEqual(aggregate.marketplaces["prom"].current_features["Color"].values, ["Black"])
        self.assertIsNotNone(aggregate.workflow.draft)
        self.assertEqual(aggregate.workflow.draft.status if aggregate.workflow.draft else None, "draft")
        self.assertIsNone(aggregate.workflow.save)


if __name__ == "__main__":
    unittest.main()
