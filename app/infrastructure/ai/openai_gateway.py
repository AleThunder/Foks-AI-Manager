from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.application.services.prompts import build_product_patch_messages
from app.application.services.product_ai import AIProductPatchModel
from app.infrastructure.logging import get_logger


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
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=timeout_seconds,
        )
        self._logger = get_logger("app.integration.openai")

    def generate_patch(self, *, context: dict[str, Any], instructions: str) -> dict[str, Any]:
        """Generate a normalized ProductPatch draft using the official OpenAI SDK."""
        completion = self._client.chat.completions.parse(
            model=self._model,
            messages=build_product_patch_messages(context=context, instructions=instructions),
            response_format=AIProductPatchModel,
            timeout=self._timeout_seconds,
        )
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise RuntimeError(f"OpenAI refused to generate a patch draft: {refusal}")
            raise RuntimeError("OpenAI response did not contain a parsed ProductPatch payload.")

        parsed_payload = AIProductPatchModel.model_validate(parsed).model_dump(mode="json")

        self._logger.info(
            "openai_patch_generated",
            extra={
                "event": "openai_patch_generated",
                "model": self._model,
                "marketplace_count": len(parsed_payload.get("marketplace_patches", [])),
            },
        )
        return parsed_payload
