from __future__ import annotations

import json
import unittest

from app.application.services.prompts import (
    PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
    PRODUCT_PATCH_SYSTEM_PROMPT,
    build_product_patch_messages,
)


class ProductPromptTests(unittest.TestCase):
    """Verify centralized prompt assembly for OpenAI product draft generation."""

    def test_build_product_patch_messages_uses_centralized_prompts(self) -> None:
        """Prompt building should reuse the centralized system and default instruction strings."""
        messages = build_product_patch_messages(
            context={"product": {"identity": {"article": "ART-777"}}},
            instructions=PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], PRODUCT_PATCH_SYSTEM_PROMPT)
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(
            json.loads(messages[1]["content"]),
            {
                "instructions": PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
                "context": {"product": {"identity": {"article": "ART-777"}}},
            },
        )


if __name__ == "__main__":
    unittest.main()
