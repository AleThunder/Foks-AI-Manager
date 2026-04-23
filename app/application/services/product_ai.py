from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import FeatureValue, ProductAggregate

AI_MARKETPLACES = ("prom", "rozetka")
AI_TEXT_FIELDS = ("nameExt", "descriptionExtRu", "nameExtUa", "descriptionExtUa")
TEXT_FIELD_LIMITS = {
    "nameExt": 255,
    "nameExtUa": 255,
    "descriptionExtRu": 12000,
    "descriptionExtUa": 12000,
}
PRODUCT_CONTEXT_FIELDS = (
    "name",
    "brand",
    "vendor",
    "manufacturer",
    "model",
    "description",
    "descriptionRu",
    "descriptionUa",
    "country",
    "countryOrigin",
    "barcode",
    "keywords",
    "keywordsUa",
)


class AIFieldPatchModel(BaseModel):
    """Describe the only marketplace text fields the AI may modify."""

    model_config = ConfigDict(extra="forbid")

    nameExt: str | None = None
    descriptionExtRu: str | None = None
    nameExtUa: str | None = None
    descriptionExtUa: str | None = None


class AIFeaturePatchModel(BaseModel):
    """Describe one normalized marketplace feature update produced by AI."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    values: list[str] = Field(default_factory=list)


class AIMarketplacePatchModel(BaseModel):
    """Describe one marketplace-scoped update in the normalized AI output."""

    model_config = ConfigDict(extra="forbid")

    market_id: Literal["prom", "rozetka"]
    fields: AIFieldPatchModel = Field(default_factory=AIFieldPatchModel)
    feature_values: list[AIFeaturePatchModel] = Field(default_factory=list)


class AIProductPatchModel(BaseModel):
    """Describe the normalized ProductPatch structure requested from OpenAI."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    offer_id: str = ""
    marketplace_patches: list[AIMarketplacePatchModel] = Field(default_factory=list)


class ProductAIContextBuilderService:
    """Build a short, stable AI context from the persisted product aggregate."""

    def build_from_aggregate(self, aggregate: ProductAggregate) -> dict[str, Any]:
        """Return only the product data required by the AI draft generation step."""
        snapshot = aggregate.latest_snapshot
        if snapshot is None:
            raise LookupError(f"Product '{aggregate.identity.article}' does not have a persisted snapshot.")

        marketplaces: list[dict[str, Any]] = []
        for market_id in AI_MARKETPLACES:
            marketplace = aggregate.marketplaces.get(market_id)
            if marketplace is None:
                continue

            feature_names = sorted(
                set(marketplace.current_features.keys()) | set(marketplace.allowed_features.keys())
            )
            features = [
                self._build_feature_context(
                    feature_name=feature_name,
                    current_feature=marketplace.current_features.get(feature_name),
                    allowed_feature=marketplace.allowed_features.get(feature_name),
                )
                for feature_name in feature_names
            ]

            marketplaces.append(
                {
                    "market_id": market_id,
                    "market_category": {
                        "id": marketplace.market_cat_id,
                        "name": marketplace.market_cat_name,
                    },
                    "texts": {
                        field_name: str(marketplace.fields.get(field_name, "") or "")
                        for field_name in AI_TEXT_FIELDS
                        if str(marketplace.fields.get(field_name, "") or "").strip()
                    },
                    "features": features,
                }
            )

        return {
            "product": {
                "identity": {
                    "internal_id": aggregate.identity.id,
                    "article": aggregate.identity.article,
                    "pid": aggregate.identity.pid,
                    "external_product_id": aggregate.identity.external_product_id,
                    "offer_id": aggregate.identity.offer_id,
                    "snapshot_id": snapshot.id,
                },
                "basic_fields": self._build_basic_fields(snapshot.basic_fields),
            },
            "marketplaces": marketplaces,
        }

    def _build_basic_fields(self, basic_fields: dict[str, Any]) -> dict[str, str]:
        """Keep only short, stable product-level fields that are useful for AI prompting."""
        result: dict[str, str] = {}
        for field_name in PRODUCT_CONTEXT_FIELDS:
            value = basic_fields.get(field_name)
            if isinstance(value, (str, int, float)) and str(value).strip():
                result[field_name] = str(value).strip()
        return result

    def _build_feature_context(
        self,
        *,
        feature_name: str,
        current_feature: FeatureValue | None,
        allowed_feature: FeatureValue | None,
    ) -> dict[str, Any]:
        """Combine current and allowed feature metadata into one compact AI-facing structure."""
        return {
            "name": feature_name,
            "current_values": list(current_feature.values if current_feature else []),
            "allowed_values": list(allowed_feature.options if allowed_feature else []),
            "required": bool(allowed_feature.required) if allowed_feature else False,
            "facet": bool((allowed_feature or current_feature).facet) if (allowed_feature or current_feature) else False,
        }
