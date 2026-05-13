from __future__ import annotations

import unittest
import json
from typing import Any

from app.application.services.product_ai import (
    MarketplaceDescriptionPartsModel,
    MarketplaceNameModel,
    MarketplaceTranslationModel,
    ProductIdentityAnalysisModel,
    ProductMarketingAnalysisModel,
)
from app.infrastructure.ai.openai_gateway import OpenAIProductPatchGateway


class FakeParsedMessage:
    """Mimic the parsed message object returned by the OpenAI SDK."""

    def __init__(self, parsed: Any) -> None:
        """Expose parsed payload and assistant content used by the gateway."""
        self.parsed = parsed
        self.refusal = None
        self.content = parsed.model_dump_json()


class FakeParsedChoice:
    """Wrap one parsed message inside a completion choice container."""

    def __init__(self, parsed: Any) -> None:
        """Build a choice with exactly one parsed message."""
        self.message = FakeParsedMessage(parsed)


class FakeParsedCompletion:
    """Mimic the parsed completion object returned by `chat.completions.parse()`."""

    def __init__(self, parsed: Any) -> None:
        """Expose one parsed choice for the gateway under test."""
        self.choices = [FakeParsedChoice(parsed)]


class FakeChatCompletions:
    """Capture parse requests and return response_format-specific parsed objects."""

    def __init__(self) -> None:
        """Prepare request capture and deterministic structured responses."""
        self.requests: list[dict[str, Any]] = []
        self._response_index_by_format: dict[type[Any], int] = {}

    def parse(self, **kwargs: Any) -> FakeParsedCompletion:
        """Record SDK call arguments and return a structured fake response."""
        self.requests.append(dict(kwargs))
        response_format = kwargs["response_format"]
        index = self._response_index_by_format.get(response_format, 0)
        self._response_index_by_format[response_format] = index + 1
        return FakeParsedCompletion(self._build_response(response_format, index, kwargs["messages"]))

    def _build_response(self, response_format: type[Any], index: int, messages: list[dict[str, str]]) -> Any:
        """Return the parsed model expected for one generation step."""
        if response_format is ProductIdentityAnalysisModel:
            return ProductIdentityAnalysisModel(
                product_type="Фен для волос",
                brand="BaByliss PRO",
                model="Falco BAB8550BE",
                additional_info="",
                category_hint="Фены",
                source_confidence=0.92,
            )
        if response_format is ProductMarketingAnalysisModel:
            return ProductMarketingAnalysisModel(
                icp="Профессиональные мастера и владельцы салонов красоты.",
                customer_pains=["Нужна быстрая сушка", "Важна надежность в потоке клиентов"],
                product_benefits=["Профессиональный мотор", "Эргономичный корпус"],
                seo_keywords=["фен для волос", "профессиональный фен"],
                marketing_angles=["для салона", "для ежедневной нагрузки"],
            )
        if response_format is MarketplaceNameModel:
            market_id = self._latest_market_id(messages, index)
            return MarketplaceNameModel(
                market_id=market_id,
                name_ru=f"Фен BaByliss PRO Falco BAB8550BE {market_id}",
            )
        if response_format is MarketplaceDescriptionPartsModel:
            market_id = self._latest_market_id(messages, index)
            return MarketplaceDescriptionPartsModel(
                market_id=market_id,
                intro_block=f"<p>{market_id} intro</p>",
                benefits_block=f"<ul><li>{market_id} benefit</li></ul>",
                usage_or_specs_block=f"<p>{market_id} specs</p>",
                trust_block=f"<p>{market_id} trust</p>",
                summary_block=f"<p>{market_id} summary</p>",
            )
        if response_format is MarketplaceTranslationModel:
            market_id = self._latest_market_id(messages, index)
            return MarketplaceTranslationModel(
                market_id=market_id,
                name_ua=f"Фен BaByliss PRO Falco BAB8550BE {market_id} UA",
                description_ua=f"<p>{market_id} опис українською</p>",
            )
        raise AssertionError(f"Unexpected response_format: {response_format}")

    def _latest_market_id(self, messages: list[dict[str, str]], index: int) -> str:
        """Extract the most recent prompt market id, falling back to the expected two-market order."""
        for message in reversed(messages):
            if message["role"] != "user":
                continue
            payload = json.loads(message["content"])
            market_id = payload.get("market_id")
            if market_id:
                return str(market_id)
        return "rozetka" if index == 0 else "prom"


class FakeChat:
    """Expose the fake completions resource under `client.chat`."""

    def __init__(self) -> None:
        """Attach the fake completions API used by the gateway."""
        self.completions = FakeChatCompletions()


class FakeClient:
    """Provide the minimal OpenAI client surface used by the gateway."""

    def __init__(self) -> None:
        """Attach the fake chat resource expected by the production gateway."""
        self.chat = FakeChat()


class OpenAIGatewayTests(unittest.TestCase):
    """Verify OpenAI gateway behavior around stepwise structured generation."""

    def test_gateway_generates_patch_with_conversation_history_per_product(self) -> None:
        """Every generation step should receive earlier messages from the same product session."""
        client = FakeClient()
        gateway = OpenAIProductPatchGateway(
            api_key="secret",
            model="gpt-5",
            client=client,
        )

        patch = gateway.generate_patch(
            context={
                "product": {
                    "identity": {"article": "ART-777"},
                    "basic_fields": {"name": "Фен для волос BaByliss PRO Falco BAB8550BE"},
                },
                "marketplaces": [
                    {"market_id": "prom", "texts": {}},
                    {"market_id": "rozetka", "texts": {}},
                ],
            },
            instructions="Improve marketplace content.",
        )

        requests = client.chat.completions.requests
        self.assertEqual(len(requests), 8)
        for request in requests:
            user_payload = json.loads(request["messages"][-1]["content"])
            self.assertEqual(user_payload["instructions"], "Improve marketplace content.")
        self.assertEqual(requests[0]["response_format"], ProductIdentityAnalysisModel)
        self.assertEqual(requests[1]["response_format"], ProductMarketingAnalysisModel)
        self.assertGreater(len(requests[1]["messages"]), len(requests[0]["messages"]))
        self.assertEqual(requests[2]["response_format"], MarketplaceNameModel)
        self.assertEqual(requests[3]["response_format"], MarketplaceDescriptionPartsModel)
        self.assertEqual(requests[4]["response_format"], MarketplaceTranslationModel)
        self.assertEqual(requests[5]["response_format"], MarketplaceNameModel)
        self.assertEqual(requests[6]["response_format"], MarketplaceDescriptionPartsModel)
        self.assertEqual(requests[7]["response_format"], MarketplaceTranslationModel)
        self.assertEqual({item["market_id"] for item in patch["marketplace_patches"]}, {"rozetka", "prom"})
        for marketplace_patch in patch["marketplace_patches"]:
            self.assertEqual(
                set(marketplace_patch["fields"].keys()),
                {"nameExt", "descriptionExtRu", "nameExtUa", "descriptionExtUa"},
            )

    def test_gateway_logs_openai_request_and_response_bodies(self) -> None:
        """OpenAI calls should be inspectable in the dedicated API log."""
        client = FakeClient()
        gateway = OpenAIProductPatchGateway(
            api_key="secret",
            model="gpt-5",
            client=client,
        )

        with self.assertLogs("app.integration.openai", level="INFO") as captured_logs:
            gateway.generate_patch(
                context={
                    "product": {"identity": {"article": "ART-777"}, "basic_fields": {"name": "Product"}},
                    "marketplaces": [],
                },
                instructions="Generate only available marketplaces.",
            )

        request_records = [
            record for record in captured_logs.records if getattr(record, "event", "") == "openai_api_request"
        ]
        response_records = [
            record for record in captured_logs.records if getattr(record, "event", "") == "openai_api_response"
        ]
        self.assertEqual(request_records[0].request_body["model"], "gpt-5")
        self.assertIn("messages", request_records[0].request_body)
        self.assertEqual(response_records[0].response_body["source_confidence"], 0.92)

    def test_gateway_resets_conversation_history_for_each_product(self) -> None:
        """Calling generate_patch twice should not reuse the previous product's messages."""
        client = FakeClient()
        gateway = OpenAIProductPatchGateway(
            api_key="secret",
            model="gpt-5",
            client=client,
        )
        context = {
            "product": {"identity": {"article": "ART-777"}, "basic_fields": {"name": "Product"}},
            "marketplaces": [{"market_id": "rozetka", "texts": {}}],
        }

        gateway.generate_patch(context=context, instructions="First product.")
        first_second_call_size = len(client.chat.completions.requests[1]["messages"])
        gateway.generate_patch(context=context, instructions="Second product.")
        second_product_first_call_size = len(client.chat.completions.requests[5]["messages"])
        second_product_second_call_size = len(client.chat.completions.requests[6]["messages"])

        self.assertEqual(second_product_first_call_size, len(client.chat.completions.requests[0]["messages"]))
        self.assertEqual(second_product_second_call_size, first_second_call_size)

    def test_gateway_returns_empty_patch_when_no_supported_marketplaces_exist(self) -> None:
        """Gateway should not invent marketplace patches when context has no target marketplaces."""
        client = FakeClient()
        gateway = OpenAIProductPatchGateway(
            api_key="secret",
            model="gpt-5",
            client=client,
        )

        patch = gateway.generate_patch(
            context={
                "product": {"identity": {"article": "ART-777"}, "basic_fields": {"name": "Product"}},
                "marketplaces": [],
            },
            instructions="Generate only available marketplaces.",
        )

        self.assertEqual(len(client.chat.completions.requests), 2)
        self.assertEqual(patch["marketplace_patches"], [])


if __name__ == "__main__":
    unittest.main()
