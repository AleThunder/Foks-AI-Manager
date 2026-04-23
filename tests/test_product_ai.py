from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_ai import ProductAIContextBuilderService
from app.application.services.product_patch_validation import ProductPatchValidationService
from app.domain.models import FeatureValue, MarketplaceMeta, MarketplaceSnapshot, ProductSnapshot
from app.infrastructure.db import ProductAggregateRepository, ProductRepository, SnapshotRepository, configure_database, upgrade_database
from app.infrastructure.settings import get_settings


class ProductAiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._database_url = f"sqlite:///{Path(self._temp_dir.name) / 'test.db'}"
        configure_database(url=self._database_url, force=True)
        upgrade_database(url=self._database_url)

        self._product_repository = ProductRepository()
        self._snapshot_repository = SnapshotRepository(product_repository=self._product_repository)
        self._aggregate_repository = ProductAggregateRepository(
            product_repository=self._product_repository,
            snapshot_repository=self._snapshot_repository,
        )

        self._snapshot_repository.save_snapshot(
            ProductSnapshot(
                article="ART-777",
                pid="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                product_id="prod-1",
                offer_id="offer-1",
                csrf_save_token="csrf-123",
                basic_fields={
                    "name": "Demo product",
                    "brand": "FOKS",
                    "descriptionUa": "Базовий опис",
                    "irrelevant": "skip me",
                },
                marketplaces={
                    "prom": MarketplaceSnapshot(
                        market_id="prom",
                        meta=MarketplaceMeta(marketid="prom", catid="cat-prom", custcatid="cust-prom"),
                        market_cat_id="cat-prom",
                        market_cat_name="Prom category",
                        fields={
                            "nameExt": "Prom title",
                            "descriptionExtRu": "<p>Prom description</p>",
                            "priceExt": "100",
                        },
                        current_features={
                            "Color": FeatureValue(name="Color", values=["Black"]),
                        },
                        allowed_features={
                            "Color": FeatureValue(
                                name="Color",
                                options=["Black", "White"],
                                required=True,
                            ),
                        },
                    ),
                    "rozetka": MarketplaceSnapshot(
                        market_id="rozetka",
                        meta=MarketplaceMeta(marketid="rozetka", catid="cat-roz", custcatid="cust-roz"),
                        market_cat_id="cat-roz",
                        market_cat_name="Rozetka category",
                        fields={
                            "nameExtUa": "Rozetka title",
                            "descriptionExtUa": "<p>Rozetka description</p>",
                        },
                        current_features={
                            "Memory": FeatureValue(name="Memory", values=["128 GB"]),
                        },
                        allowed_features={
                            "Memory": FeatureValue(
                                name="Memory",
                                options=["64 GB", "128 GB"],
                            ),
                        },
                    ),
                    "other": MarketplaceSnapshot(
                        market_id="other",
                        meta=MarketplaceMeta(marketid="other"),
                        fields={"nameExt": "Other title"},
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

    def test_context_builder_returns_short_stable_context_for_prom_and_rozetka(self) -> None:
        aggregate = self._aggregate_repository.get_latest_aggregate_by_article("ART-777")
        assert aggregate is not None

        context = ProductAIContextBuilderService().build_from_aggregate(aggregate)

        self.assertEqual(context["product"]["identity"]["article"], "ART-777")
        self.assertEqual(context["product"]["basic_fields"]["name"], "Demo product")
        self.assertNotIn("irrelevant", context["product"]["basic_fields"])
        self.assertEqual([item["market_id"] for item in context["marketplaces"]], ["prom", "rozetka"])
        self.assertEqual(context["marketplaces"][0]["texts"]["nameExt"], "Prom title")
        self.assertNotIn("priceExt", context["marketplaces"][0]["texts"])
        self.assertEqual(context["marketplaces"][1]["features"][0]["allowed_values"], ["64 GB", "128 GB"])

    def test_validator_rejects_unknown_fields_and_invalid_feature_values(self) -> None:
        aggregate = self._aggregate_repository.get_latest_aggregate_by_article("ART-777")
        assert aggregate is not None

        validation = ProductPatchValidationService().validate(
            aggregate=aggregate,
            raw_patch={
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "basic_fields": {"name": "Forbidden"},
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {
                            "nameExt": "Clean title",
                            "priceExt": "123",
                        },
                        "feature_values": [
                            {"name": "Color", "values": ["Blue"]},
                        ],
                    }
                ],
            },
        )

        self.assertEqual(validation.patch.marketplace_patches["prom"].fields["nameExt"], "Clean title")
        self.assertIn("AI draft cannot modify top-level basic_fields.", validation.errors)
        self.assertTrue(any("Field 'priceExt'" in error for error in validation.errors))
        self.assertTrue(any("invalid values" in error for error in validation.errors))


if __name__ == "__main__":
    unittest.main()
