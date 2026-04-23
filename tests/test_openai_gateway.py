from __future__ import annotations

import json
import unittest

from app.application.services.prompts import PRODUCT_PATCH_SYSTEM_PROMPT
from app.application.services.product_ai import AIProductPatchModel
from app.infrastructure.ai.openai_gateway import OpenAIProductPatchGateway


class FakeParsedMessage:
    """Mimic the parsed message object returned by the OpenAI SDK."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Expose the parsed payload and refusal fields used by the gateway."""
        self.parsed = parsed
        self.refusal = None


class FakeParsedChoice:
    """Wrap one parsed message inside a completion choice container."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Build a choice with exactly one parsed message."""
        self.message = FakeParsedMessage(parsed)


class FakeParsedCompletion:
    """Mimic the parsed completion object returned by `chat.completions.parse()`."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Expose one parsed choice for the gateway under test."""
        self.choices = [FakeParsedChoice(parsed)]


class FakeChatCompletions:
    """Capture parse requests and return a canned parsed completion."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Store the completion returned by the fake `parse()` call."""
        self._completion = FakeParsedCompletion(parsed)
        self.last_request: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> FakeParsedCompletion:
        """Record the SDK call arguments and return the prepared completion."""
        self.last_request = dict(kwargs)
        return self._completion


class FakeChat:
    """Expose the fake completions resource under `client.chat`."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Attach the fake completions API used by the gateway."""
        self.completions = FakeChatCompletions(parsed)


class FakeClient:
    """Provide the minimal OpenAI client surface used by the gateway."""

    def __init__(self, parsed: AIProductPatchModel) -> None:
        """Attach the fake chat resource expected by the production gateway."""
        self.chat = FakeChat(parsed)


class OpenAIGatewayTests(unittest.TestCase):
    """Verify OpenAI gateway behavior around structured SDK parsing."""

    def test_gateway_uses_sdk_parse_and_parses_structured_response(self) -> None:
        """Gateway calls should use centralized prompts and parse into normalized drafts."""
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
