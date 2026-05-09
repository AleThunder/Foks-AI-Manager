from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from openai import OpenAI

from app.application.services.prompts import (
    build_identity_analysis_messages,
    build_marketplace_description_messages,
    build_marketplace_name_messages,
    build_marketplace_translation_messages,
    build_marketing_analysis_messages,
)
from app.application.services.product_ai import (
    AIProductPatchModel,
    MarketplaceDescriptionPartsModel,
    MarketplaceNameModel,
    MarketplaceTranslationModel,
    ProductIdentityAnalysisModel,
    ProductMarketingAnalysisModel,
)
from app.infrastructure.logging import get_logger

MARKETPLACE_GENERATION_ORDER = ("rozetka", "prom")


class OpenAIProductPatchGateway:
    """Call OpenAI with Structured Outputs and return a normalized ProductPatch draft payload."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        """Store OpenAI SDK settings and a reusable client instance."""
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )
        self._logger = get_logger("app.integration.openai")

    def generate_patch(self, *, context: dict[str, Any], instructions: str) -> dict[str, Any]:
        """Generate a normalized ProductPatch draft through stepwise marketplace text calls."""
        messages: list[dict[str, str]] = []
        identity = self._run_step(
            messages=messages,
            step_messages=build_identity_analysis_messages(
                context=context,
                instructions=instructions,
            ),
            response_format=ProductIdentityAnalysisModel,
        )
        marketing = self._run_step(
            messages=messages,
            step_messages=build_marketing_analysis_messages(
                context=context,
                identity=identity,
                instructions=instructions,
            ),
            response_format=ProductMarketingAnalysisModel,
        )

        marketplace_patches: list[dict[str, Any]] = []
        for market_id in self._selected_marketplaces(context):
            name = self._run_step(
                messages=messages,
                step_messages=build_marketplace_name_messages(
                    context=context,
                    identity=identity,
                    marketing=marketing,
                    market_id=market_id,
                    instructions=instructions,
                ),
                response_format=MarketplaceNameModel,
            )
            self._ensure_marketplace_response(market_id=market_id, response_market_id=name.market_id)

            description = self._run_step(
                messages=messages,
                step_messages=build_marketplace_description_messages(
                    context=context,
                    identity=identity,
                    marketing=marketing,
                    market_id=market_id,
                    name_ru=name.name_ru,
                    instructions=instructions,
                ),
                response_format=MarketplaceDescriptionPartsModel,
            )
            self._ensure_marketplace_response(market_id=market_id, response_market_id=description.market_id)

            translation = self._run_step(
                messages=messages,
                step_messages=build_marketplace_translation_messages(
                    context=context,
                    market_id=market_id,
                    name_ru=name.name_ru,
                    description_ru=description.description_ru,
                    instructions=instructions,
                ),
                response_format=MarketplaceTranslationModel,
            )
            self._ensure_marketplace_response(market_id=market_id, response_market_id=translation.market_id)

            marketplace_patches.append(
                {
                    "market_id": market_id,
                    "fields": {
                        "nameExt": name.name_ru,
                        "descriptionExtRu": description.description_ru,
                        "nameExtUa": translation.name_ua,
                        "descriptionExtUa": translation.description_ua,
                    },
                    "feature_values": [],
                }
            )

        product_identity = dict(context.get("product", {}).get("identity", {}))
        parsed_payload = AIProductPatchModel.model_validate(
            {
                "product_id": str(
                    product_identity.get("external_product_id")
                    or product_identity.get("product_id")
                    or product_identity.get("internal_id")
                    or product_identity.get("article")
                    or ""
                ),
                "offer_id": str(product_identity.get("offer_id", "") or ""),
                "marketplace_patches": marketplace_patches,
            }
        ).model_dump(mode="json")

        self._logger.info(
            "openai_patch_generated",
            extra={
                "event": "openai_patch_generated",
                "model": self._model,
                "marketplace_count": len(parsed_payload.get("marketplace_patches", [])),
                "generation_step_count": len(messages),
            },
        )
        return parsed_payload

    def _run_step(
        self,
        *,
        messages: list[dict[str, str]],
        step_messages: list[dict[str, str]],
        response_format: type[BaseModel],
    ) -> Any:
        """Run one structured generation step and append the exchange to product-local history."""
        messages.extend(step_messages)
        request_body = {
            "model": self._model,
            "messages": list(messages),
            "response_format": response_format.__name__,
            "timeout": self._timeout_seconds,
        }
        self._logger.info(
            "openai_api_request",
            extra={
                "event": "openai_api_request",
                "model": self._model,
                "response_format": response_format.__name__,
                "request_body": request_body,
            },
        )
        completion = self._client.chat.completions.parse(
            model=self._model,
            messages=list(messages),
            response_format=response_format,
            timeout=self._timeout_seconds,
        )
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise RuntimeError(f"OpenAI refused to generate a structured product text step: {refusal}")
            raise RuntimeError("OpenAI response did not contain a parsed structured product text payload.")

        parsed_model = response_format.model_validate(parsed)
        response_body = parsed_model.model_dump(mode="json")
        self._logger.info(
            "openai_api_response",
            extra={
                "event": "openai_api_response",
                "model": self._model,
                "response_format": response_format.__name__,
                "response_body": response_body,
            },
        )
        messages.append({"role": "assistant", "content": self._serialize_assistant_content(parsed_model)})
        return parsed_model

    def _selected_marketplaces(self, context: dict[str, Any]) -> list[str]:
        """Return marketplace ids present in context in the generation order requested by the business flow."""
        present_marketplaces = {
            str(marketplace.get("market_id"))
            for marketplace in context.get("marketplaces", [])
            if isinstance(marketplace, dict) and marketplace.get("market_id")
        }
        return [
            market_id
            for market_id in MARKETPLACE_GENERATION_ORDER
            if market_id in present_marketplaces
        ]

    def _ensure_marketplace_response(self, *, market_id: str, response_market_id: str) -> None:
        """Reject structured responses that drift into another marketplace's payload."""
        if response_market_id != market_id:
            raise RuntimeError(
                f"OpenAI generated '{response_market_id}' content while '{market_id}' was requested."
            )

    def _serialize_assistant_content(self, parsed_model: BaseModel) -> str:
        """Serialize parsed model output as an assistant history message for later steps."""
        return json.dumps(parsed_model.model_dump(mode="json"), ensure_ascii=False)
