from __future__ import annotations

import json
import unittest

from app.application.services.prompts import PRODUCT_PATCH_SYSTEM_PROMPT
from app.application.services.product_ai import AIProductPatchModel
from app.infrastructure.ai.openai_gateway import OpenAIProductPatchGateway


class FakeParsedMessage:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self.parsed = parsed
        self.refusal = None


class FakeParsedChoice:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self.message = FakeParsedMessage(parsed)


class FakeParsedCompletion:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self.choices = [FakeParsedChoice(parsed)]


class FakeChatCompletions:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self._completion = FakeParsedCompletion(parsed)
        self.last_request: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> FakeParsedCompletion:
        self.last_request = dict(kwargs)
        return self._completion


class FakeChat:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self.completions = FakeChatCompletions(parsed)


class FakeClient:
    def __init__(self, parsed: AIProductPatchModel) -> None:
        self.chat = FakeChat(parsed)


class OpenAIGatewayTests(unittest.TestCase):
    def test_gateway_uses_sdk_parse_and_parses_structured_response(self) -> None:
        parsed_patch = AIProductPatchModel.model_validate(
            {
                "product_id": "prod-1",
                "offer_id": "offer-1",
                "marketplace_patches": [
                    {
                        "market_id": "prom",
                        "fields": {"nameExt": "New title"},
                        "feature_values": [],
                    }
                ],
            }
        )
        client = FakeClient(parsed_patch)
        gateway = OpenAIProductPatchGateway(
            api_key="secret",
            model="gpt-5",
            client=client,
        )

        patch = gateway.generate_patch(
            context={"product": {"identity": {"article": "ART-777"}}, "marketplaces": []},
            instructions="Improve the title.",
        )

        request_payload = client.chat.completions.last_request
        assert request_payload is not None
        self.assertEqual(request_payload["model"], "gpt-5")
        self.assertIs(request_payload["response_format"], AIProductPatchModel)
        self.assertEqual(request_payload["messages"][0]["content"], PRODUCT_PATCH_SYSTEM_PROMPT)
        self.assertEqual(
            json.loads(request_payload["messages"][1]["content"])["instructions"],
            "Improve the title.",
        )
        self.assertEqual(patch["marketplace_patches"][0]["fields"]["nameExt"], "New title")


if __name__ == "__main__":
    unittest.main()
