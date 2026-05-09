from __future__ import annotations

import json
from typing import Any, Literal

from app.application.services.product_ai import ProductIdentityAnalysisModel, ProductMarketingAnalysisModel

PRODUCT_PATCH_SYSTEM_PROMPT = (
    "You generate normalized ProductPatch drafts for FOKS products. Return JSON only. "
    "Never modify top-level basic_fields, flags, category ids, pricing, photos, or raw FOKS payload keys. "
    "Only marketplace text fields for prom and rozetka may be generated."
)

PRODUCT_PATCH_DEFAULT_INSTRUCTIONS = (
    "Generate marketplace titles and descriptions for Prom and Rozetka using the product's main Beauty Mafia "
    "name and description as analysis input. Return only fields that should change."
)

PROMPT_PRIORITY_RULES = (
    "Priority order: 1) FoksApp technical validator limits, 2) UpScale PromptData rules, "
    "3) FOKS PDF instructions, 4) product text rules PDF, 5) request-specific instructions. "
    "The UpScale PromptData rules are the main content source: SEO and LSI copywriting, human-written style, "
    "pragmatic selling tone, no keyword stuffing, and benefits based on ICP, customer pains, and real product facts. "
    "Titles follow the structure 'Тип товару Бренд Модель Додаткова інформація' and must stay до 70 символів "
    "(up to 70 characters) "
    "when possible. Rozetka needs a new Russian name and description; Ukrainian texts are translated/adapted from "
    "the generated Russian version. Prom follows the Rozetka logic but is generated as its own unique marketplace text."
)

HTML_RULES = (
    "Descriptions may use only minimal safe HTML supported by the FoksApp sanitizer: "
    "<p>, <ul>, <ol>, <li>, <br>, <strong>, <em>, <b>, <i>. Do not use h2/h3, scripts, styles, classes, ids, "
    "tables, images, schema markup, or nested product cards."
)


def build_product_patch_messages(*, context: dict[str, Any], instructions: str) -> list[dict[str, str]]:
    """Build the legacy one-shot prompt shape retained for compatibility with older tests/callers."""
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


def build_identity_analysis_messages(
    *,
    context: dict[str, Any],
    instructions: str,
) -> list[dict[str, str]]:
    """Build the prompt that extracts stable product identity before generation starts."""
    system_prompt = (
        f"{PRODUCT_PATCH_SYSTEM_PROMPT} {PROMPT_PRIORITY_RULES} "
        "Analyze the source product name and description. Infer only facts supported by the context. "
        "Extract product type, brand, model, useful additional info, and category hint. "
        "Do not generate final marketplace text in this step."
    )
    return _messages(
        system_prompt=system_prompt,
        payload={
            "task": "identity_analysis",
            "instructions": instructions,
            "context": context,
            "output_contract": ProductIdentityAnalysisModel.model_json_schema(),
        },
    )


def build_marketing_analysis_messages(
    *,
    context: dict[str, Any],
    identity: ProductIdentityAnalysisModel,
    instructions: str,
) -> list[dict[str, str]]:
    """Build the combined ICP, pain, benefit, and SEO analysis prompt."""
    system_prompt = (
        f"{PRODUCT_PATCH_SYSTEM_PROMPT} {PROMPT_PRIORITY_RULES} "
        "Create one shared marketing analysis for this product: ICP, customer pains, product benefits, SEO keywords, "
        "and marketing angles. This combines the old separate ICP, pain, and benefit steps so later field prompts "
        "share one coherent strategic context."
    )
    return _messages(
        system_prompt=system_prompt,
        payload={
            "task": "marketing_analysis",
            "instructions": instructions,
            "identity": identity.model_dump(mode="json"),
            "context": context,
            "output_contract": ProductMarketingAnalysisModel.model_json_schema(),
        },
    )


def build_marketplace_name_messages(
    *,
    context: dict[str, Any],
    identity: ProductIdentityAnalysisModel,
    marketing: ProductMarketingAnalysisModel,
    market_id: Literal["prom", "rozetka"],
    instructions: str,
) -> list[dict[str, str]]:
    """Build the prompt for one marketplace Russian title."""
    system_prompt = (
        f"{PRODUCT_PATCH_SYSTEM_PROMPT} {PROMPT_PRIORITY_RULES} "
        "Generate only one Russian marketplace title. Keep it clear, unique, readable, and до 70 символів "
        "(up to 70 characters) "
        "when possible. Use product type, brand, model, and only the most useful additional info. "
        "Do not use special symbols such as &, emoji, quotes for decoration, or unsupported claims."
    )
    return _messages(
        system_prompt=system_prompt,
        payload={
            "task": "marketplace_name_ru",
            "instructions": instructions,
            "market_id": market_id,
            "identity": identity.model_dump(mode="json"),
            "marketing": marketing.model_dump(mode="json"),
            "context": context,
        },
    )


def build_marketplace_description_messages(
    *,
    context: dict[str, Any],
    identity: ProductIdentityAnalysisModel,
    marketing: ProductMarketingAnalysisModel,
    market_id: Literal["prom", "rozetka"],
    name_ru: str,
    instructions: str,
) -> list[dict[str, str]]:
    """Build the prompt for one marketplace Russian description split into editable blocks."""
    system_prompt = (
        f"{PRODUCT_PATCH_SYSTEM_PROMPT} {PROMPT_PRIORITY_RULES} {HTML_RULES} "
        "Generate the Russian description as separate blocks: intro_block, benefits_block, usage_or_specs_block, "
        "trust_block, summary_block. Each block must focus on a distinct purpose so it can be tuned independently. "
        "Use ICP, pains, benefits, and real characteristics; do not repeat delivery/payment/discount FAQ content."
    )
    return _messages(
        system_prompt=system_prompt,
        payload={
            "task": "marketplace_description_ru_parts",
            "instructions": instructions,
            "market_id": market_id,
            "name_ru": name_ru,
            "identity": identity.model_dump(mode="json"),
            "marketing": marketing.model_dump(mode="json"),
            "context": context,
        },
    )


def build_marketplace_translation_messages(
    *,
    context: dict[str, Any],
    market_id: Literal["prom", "rozetka"],
    name_ru: str,
    description_ru: str,
    instructions: str,
) -> list[dict[str, str]]:
    """Build the prompt for Ukrainian text adapted from generated Russian text."""
    system_prompt = (
        f"{PRODUCT_PATCH_SYSTEM_PROMPT} {PROMPT_PRIORITY_RULES} {HTML_RULES} "
        "Translate and lightly adapt the generated Russian marketplace title and description into Ukrainian "
        "без додавання нових фактів. Preserve product facts, HTML structure, benefits, and selling intent. "
        "Return only Ukrainian marketplace text."
    )
    return _messages(
        system_prompt=system_prompt,
        payload={
            "task": "marketplace_translation_ua",
            "instructions": instructions,
            "market_id": market_id,
            "name_ru": name_ru,
            "description_ru": description_ru,
            "context": context,
        },
    )


def _messages(*, system_prompt: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    """Serialize one structured prompt payload in the chat message shape used by the gateway."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
