from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.services.product_ai import (
    AIProductPatchModel,
    MarketplaceDescriptionPartsModel,
    MarketplaceNameModel,
    MarketplaceTranslationModel,
    ProductAIContextBuilderService,
    ProductIdentityAnalysisModel,
    ProductMarketingAnalysisModel,
)
from app.application.services.product_patch_validation import ProductPatchValidationService
from app.domain.models import FeatureValue, MarketplaceMeta, MarketplaceSnapshot, ProductSnapshot
from app.infrastructure.db import ProductAggregateRepository, ProductRepository, SnapshotRepository, configure_database, upgrade_database
from app.infrastructure.settings import get_settings


class ProductAiServiceTests(unittest.TestCase):
    """Cover AI context building and draft validation against persisted aggregates."""

    def setUp(self) -> None:
        """Seed an isolated database with one product aggregate for AI-facing tests."""
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
        """Restore the default application database configuration after each test."""
        settings = get_settings()
        configure_database(
            url=settings.sqlalchemy_database_url,
            echo=settings.db_echo,
            force=True,
        )
        self._temp_dir.cleanup()

    def test_context_builder_returns_short_stable_context_for_prom_and_rozetka(self) -> None:
        """Context building should keep only the stable product slice needed by AI."""
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
        """Validation should reject non-allowlisted fields and schema-invalid feature values."""
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

    def test_ai_step_models_validate_intermediate_generation_payloads(self) -> None:
        """Intermediate AI payloads should be typed before they are assembled into a patch."""
        identity = ProductIdentityAnalysisModel(
            product_type="Фен для волос",
            brand="BaByliss PRO",
            model="Falco BAB8550BE",
            additional_info="чорний",
            category_hint="Фени",
            source_confidence=0.95,
        )
        marketing = ProductMarketingAnalysisModel(
            icp="Власники салонів краси.",
            customer_pains=["Потрібна надійність"],
            product_benefits=["Професійний мотор"],
            seo_keywords=["фен для волосся"],
            marketing_angles=["для щоденного використання"],
        )
        name = MarketplaceNameModel(market_id="rozetka", name_ru="Фен BaByliss PRO Falco BAB8550BE")
        description = MarketplaceDescriptionPartsModel(
            market_id="rozetka",
            intro_block="<p>Intro</p>",
            benefits_block="<ul><li>Benefit</li></ul>",
            usage_or_specs_block="<p>Specs</p>",
            trust_block="<p>Trust</p>",
            summary_block="<p>Summary</p>",
        )
        translation = MarketplaceTranslationModel(
            market_id="rozetka",
            name_ua="Фен BaByliss PRO Falco BAB8550BE",
            description_ua="<p>Опис українською</p>",
        )

        patch = AIProductPatchModel.model_validate(
            {
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": name.market_id,
                        "fields": {
                            "nameExt": name.name_ru,
                            "descriptionExtRu": description.description_ru,
                            "nameExtUa": translation.name_ua,
                            "descriptionExtUa": translation.description_ua,
                        },
                    }
                ],
            }
        )

        self.assertEqual(identity.brand, "BaByliss PRO")
        self.assertEqual(marketing.customer_pains, ["Потрібна надійність"])
        self.assertIn("<p>Summary</p>", description.description_ru)
        self.assertEqual(patch.marketplace_patches[0].fields.nameExt, name.name_ru)

    def test_marketplace_name_model_rejects_titles_over_seventy_characters(self) -> None:
        """Marketplace titles should enforce the SEO/business limit in schema validation."""
        with self.assertRaises(ValueError):
            MarketplaceNameModel(
                market_id="rozetka",
                name_ru="X" * 71,
            )

    def test_marketplace_translation_model_rejects_ua_titles_over_seventy_characters(self) -> None:
        """Translated marketplace titles should use the same SEO/business limit as Russian titles."""
        with self.assertRaises(ValueError):
            MarketplaceTranslationModel(
                market_id="rozetka",
                name_ua="X" * 71,
                description_ua="<p>Опис українською</p>",
            )


if __name__ == "__main__":
    unittest.main()
