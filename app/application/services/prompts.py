from __future__ import annotations

import json
from typing import Any

PRODUCT_PATCH_SYSTEM_PROMPT = (
    "You generate normalized ProductPatch drafts for FOKS products. "
    "Return JSON only. "
    "Do not output raw HTML forms, flat FOKS keys, pricing fields, flags, category ids, or unrelated marketplaces. "
    "Only include marketplace_patches for prom and rozetka, only include fields that should change, "
    "and keep feature values inside the allowed schema when options are provided."
)

PRODUCT_PATCH_DEFAULT_INSTRUCTIONS = (
    "Generate a normalized ProductPatch draft for Prom and Rozetka. "
    "Update only marketplace titles, descriptions, and allowed feature values when a real improvement is needed. "
    "Return only fields that should change."
)


def build_product_patch_messages(*, context: dict[str, Any], instructions: str) -> list[dict[str, str]]:
    """Build the full chat prompt for normalized product patch generation."""
    return [
        {"role": "system", "content": PRODUCT_PATCH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instructions": instructions,
                    "context": context,
                },
                ensure_ascii=False,
            ),
        },
    ]
