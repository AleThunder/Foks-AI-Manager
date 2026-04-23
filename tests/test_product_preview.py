from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_aggregate import GetProductAggregateService
from app.application.services.product_ai import ProductAIContextBuilderService
from app.application.services.product_patch_validation import ProductPatchValidationService
from app.application.services.product_preview import PreviewProductPatchService
from app.domain.models import FeatureValue, MarketplaceMeta, MarketplaceSnapshot, ProductSnapshot
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


class FakePatchGenerator:
    def __init__(self, response_payload: dict[str, object]) -> None:
        self.response_payload = response_payload

    def generate_patch(self, *, context: dict[str, object], instructions: str) -> dict[str, object]:
        self.last_context = context
        self.last_instructions = instructions
        return self.response_payload


class ProductPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._database_url = f"sqlite:///{Path(self._temp_dir.name) / 'test.db'}"
        configure_database(url=self._database_url, force=True)
        upgrade_database(url=self._database_url)

        self._product_repository = ProductRepository()
        self._snapshot_repository = SnapshotRepository(product_repository=self._product_repository)
        self._patch_repository = PatchRepository()
        self._task_repository = TaskRepository()
        self._aggregate_repository = ProductAggregateRepository(
            product_repository=self._product_repository,
            snapshot_repository=self._snapshot_repository,
        )
        self._aggregate_service = GetProductAggregateService(
            aggregate_repository=self._aggregate_repository,
        )

        self._snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-123",
                basic_fields={"name": "Demo product", "brand": "FOKS"},
                marketplaces={
                    "prom": MarketplaceSnapshot(
                        market_id="prom",
                        meta=MarketplaceMeta(marketid="prom", catid="cat-prom"),
                        market_cat_id="cat-prom",
                        market_cat_name="Prom category",
                        fields={
                            "nameExt": "Old title",
                            "descriptionExtRu": "<p>Old description</p>",
                        },
                        current_features={
                            "Color": FeatureValue(name="Color", values=["Black"]),
                        },
                        allowed_features={
                            "Color": FeatureValue(name="Color", options=["Black", "White"], required=True),
                        },
                    ),
                    "rozetka": MarketplaceSnapshot(
                        market_id="rozetka",
                        meta=MarketplaceMeta(marketid="rozetka", catid="cat-roz"),
                        market_cat_id="cat-roz",
                        market_cat_name="Rozetka category",
                        fields={"nameExtUa": "Old title ua"},
                        current_features={},
                        allowed_features={},
                    ),
                },
            )
        )

    def tearDown(self) -> None:
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_preview_service_persists_draft_with_diff_summary(self) -> None:
        service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            ai_context_builder=ProductAIContextBuilderService(),
            patch_validator=ProductPatchValidationService(),
            patch_generator=FakePatchGenerator(
                {
                    "product_id": "prod-1",
                    "offer_id": "offer-1",
                    "marketplace_patches": [
                        {
                            "market_id": "prom",
                            "fields": {
                                "nameExt": "New title",
                                "descriptionExtRu": "<script>alert(1)</script><p>Better description</p>",
                            },
                            "feature_values": [
                                {"name": "Color", "values": ["White"]},
                            ],
                        }
                    ],
                }
            ),
        )

        persisted_patch = service.preview(article="ART-777", instructions="Improve the listing.")

        self.assertEqual(persisted_patch.status, "draft")
        self.assertEqual(persisted_patch.patch.marketplace_patches["prom"].fields["nameExt"], "New title")
        self.assertEqual(
            persisted_patch.patch.marketplace_patches["prom"].fields["descriptionExtRu"],
            "<p>Better description</p>",
        )
        self.assertTrue(persisted_patch.base_snapshot_id)
        self.assertEqual(persisted_patch.diff_summary["change_count"], 3)
        self.assertTrue(any("sanitized" in warning for warning in persisted_patch.validation_warnings))
        self.assertEqual(persisted_patch.validation_errors, [])

    def test_preview_service_marks_invalid_manual_draft_as_failed(self) -> None:
        service = PreviewProductPatchService(
            aggregate_service=self._aggregate_service,
            patch_repository=self._patch_repository,
            task_repository=self._task_repository,
            patch_generator=None,
        )

        persisted_patch = service.preview(
            article="ART-777",
            raw_draft={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"priceExt": "123"},
                        "feature_values": [{"name": "Unknown", "values": ["x"]}],
                    }
                ],
            },
        )

        self.assertEqual(persisted_patch.status, "failed")
        self.assertTrue(any("priceExt" in error for error in persisted_patch.validation_errors))
        self.assertTrue(any("Unknown" in error for error in persisted_patch.validation_errors))


if __name__ == "__main__":
    unittest.main()
