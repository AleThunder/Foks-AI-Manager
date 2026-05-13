from __future__ import annotations

import json
import unittest

from app.application.services.prompts import (
    PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
    build_identity_analysis_messages,
    build_marketplace_description_messages,
    build_marketplace_name_messages,
    build_marketplace_translation_messages,
    build_marketing_analysis_messages,
)
from app.application.services.product_ai import (
    ProductIdentityAnalysisModel,
    ProductMarketingAnalysisModel,
)


class ProductPromptTests(unittest.TestCase):
    """Verify centralized prompt assembly for OpenAI product draft generation."""

    def test_identity_prompt_includes_priority_rules_and_product_context(self) -> None:
        """Identity analysis should expose product facts and the highest-priority prompt rules."""
        messages = build_identity_analysis_messages(
            context={
                "product": {
                    "identity": {"article": "ART-777"},
                    "basic_fields": {
                        "name": "Фен для волос BaByliss PRO Falco BAB8550BE",
                        "description": "Профессиональный фен для салона красоты.",
                    },
                },
                "marketplaces": [],
            },
            instructions=PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        prompt_payload = json.loads(messages[1]["content"])
        self.assertEqual(prompt_payload["context"]["product"]["identity"]["article"], "ART-777")
        self.assertIn("UpScale PromptData", messages[0]["content"])
        self.assertIn("Тип товару Бренд Модель", messages[0]["content"])
        self.assertIn("top-level basic_fields", messages[0]["content"])

    def test_marketplace_prompt_builders_keep_generation_steps_separate(self) -> None:
        """Each field generation step should have its own prompt surface and marketplace id."""
        identity = ProductIdentityAnalysisModel(
            product_type="Фен для волос",
            brand="BaByliss PRO",
            model="Falco BAB8550BE",
            additional_info="",
            category_hint="Фены",
            source_confidence=0.9,
        )
        marketing = ProductMarketingAnalysisModel(
            icp="Владельцы салонов красоты.",
            customer_pains=["Нужна надежность", "Важна скорость сушки"],
            product_benefits=["Профессиональный мотор", "Эргономичный корпус"],
            seo_keywords=["фен для волос", "профессиональный фен"],
            marketing_angles=["для салона"],
        )

        marketing_messages = build_marketing_analysis_messages(
            context={"product": {"basic_fields": {"name": "Original"}}},
            identity=identity,
            instructions="Keep marketplace text concise.",
        )

        name_messages = build_marketplace_name_messages(
            context={"product": {"basic_fields": {"name": "Original"}}},
            identity=identity,
            marketing=marketing,
            market_id="rozetka",
            instructions="Keep marketplace text concise.",
        )
        description_messages = build_marketplace_description_messages(
            context={"product": {"basic_fields": {"description": "Original description"}}},
            identity=identity,
            marketing=marketing,
            market_id="prom",
            instructions="Keep marketplace text concise.",
            name_ru="Фен BaByliss PRO Falco BAB8550BE",
        )
        translation_messages = build_marketplace_translation_messages(
            context={"product": {"identity": {"article": "ART-777"}}},
            market_id="rozetka",
            instructions="Keep marketplace text concise.",
            name_ru="Фен BaByliss PRO Falco BAB8550BE",
            description_ru="<p>Описание</p>",
        )

        self.assertIn('"market_id": "rozetka"', name_messages[1]["content"])
        self.assertEqual(
            json.loads(marketing_messages[1]["content"])["instructions"],
            "Keep marketplace text concise.",
        )
        self.assertEqual(json.loads(name_messages[1]["content"])["instructions"], "Keep marketplace text concise.")
        self.assertEqual(
            json.loads(description_messages[1]["content"])["instructions"],
            "Keep marketplace text concise.",
        )
        self.assertEqual(
            json.loads(translation_messages[1]["content"])["instructions"],
            "Keep marketplace text concise.",
        )
        self.assertIn("до 70", name_messages[0]["content"])
        self.assertIn("intro_block", description_messages[0]["content"])
        self.assertIn('"market_id": "prom"', description_messages[1]["content"])
        self.assertIn("без додавання нових фактів", translation_messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
