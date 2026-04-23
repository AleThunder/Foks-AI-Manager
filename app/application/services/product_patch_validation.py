from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from app.application.services.product_ai import AI_MARKETPLACES, AI_TEXT_FIELDS, TEXT_FIELD_LIMITS
from app.domain.models import FeatureValue, MarketplacePatch, ProductAggregate, ProductPatch

ALLOWED_DESCRIPTION_TAGS = {"p", "ul", "ol", "li", "br", "strong", "em", "b", "i"}
TITLE_FIELDS = {"nameExt", "nameExtUa"}


@dataclass(slots=True)
class ProductPatchValidationResult:
    """Hold the normalized draft patch together with validation output and diff metadata."""

    patch: ProductPatch
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    diff_summary: dict[str, Any] = field(default_factory=dict)


class ProductPatchValidationService:
    """Validate and normalize AI/manual patch drafts against the latest persisted aggregate."""

    def validate(
        self,
        *,
        aggregate: ProductAggregate,
        raw_patch: dict[str, Any],
        allowed_marketplaces: list[str] | None = None,
    ) -> ProductPatchValidationResult:
        """Return a normalized patch together with validation warnings, errors, and diff summary."""
        warnings: list[str] = []
        errors: list[str] = []

        snapshot = aggregate.latest_snapshot
        if snapshot is None:
            raise LookupError(f"Product '{aggregate.identity.article}' does not have a persisted snapshot.")

        if raw_patch.get("basic_fields"):
            errors.append("AI draft cannot modify top-level basic_fields.")
        if raw_patch.get("flags"):
            errors.append("AI draft cannot modify top-level flags.")

        selected_marketplaces = tuple(allowed_marketplaces or AI_MARKETPLACES)
        raw_marketplace_patches = raw_patch.get("marketplace_patches") or []
        if not isinstance(raw_marketplace_patches, list):
            errors.append("marketplace_patches must be an array.")
            raw_marketplace_patches = []

        normalized_marketplace_patches: dict[str, MarketplacePatch] = {}
        seen_marketplaces: set[str] = set()

        for raw_marketplace_patch in raw_marketplace_patches:
            if not isinstance(raw_marketplace_patch, dict):
                errors.append("Each marketplace patch must be an object.")
                continue

            market_id = str(raw_marketplace_patch.get("market_id", "") or "").strip()
            if market_id not in selected_marketplaces:
                errors.append(f"Marketplace '{market_id or '?'}' is not allowed for AI drafts.")
                continue
            if market_id in seen_marketplaces:
                errors.append(f"Marketplace '{market_id}' appears more than once in the draft.")
                continue
            seen_marketplaces.add(market_id)

            base_marketplace = aggregate.marketplaces.get(market_id)
            if base_marketplace is None:
                errors.append(f"Marketplace '{market_id}' is missing from the persisted snapshot.")
                continue

            normalized_fields = self._normalize_fields(
                market_id=market_id,
                raw_fields=raw_marketplace_patch.get("fields") or {},
                warnings=warnings,
                errors=errors,
            )
            normalized_feature_values = self._normalize_features(
                market_id=market_id,
                raw_feature_values=raw_marketplace_patch.get("feature_values") or [],
                base_marketplace=base_marketplace,
                warnings=warnings,
                errors=errors,
            )

            normalized_marketplace_patches[market_id] = MarketplacePatch(
                market_id=market_id,
                market_cat_id=base_marketplace.market_cat_id,
                market_cat_name=base_marketplace.market_cat_name,
                fields=normalized_fields,
                feature_values=normalized_feature_values,
            )

        patch = ProductPatch(
            product_id=str(raw_patch.get("product_id") or snapshot.product_id),
            offer_id=str(raw_patch.get("offer_id") or snapshot.offer_id),
            basic_fields={},
            flags={},
            marketplace_patches=normalized_marketplace_patches,
        )
        diff_summary = self._build_diff_summary(aggregate=aggregate, patch=patch)
        if diff_summary["change_count"] == 0:
            warnings.append("Draft does not change any persisted marketplace texts or feature values.")

        return ProductPatchValidationResult(
            patch=patch,
            warnings=warnings,
            errors=errors,
            diff_summary=diff_summary,
        )

    def _normalize_fields(
        self,
        *,
        market_id: str,
        raw_fields: Any,
        warnings: list[str],
        errors: list[str],
    ) -> dict[str, str]:
        """Validate allowed field names, lengths, and sanitized HTML content."""
        if not isinstance(raw_fields, dict):
            errors.append(f"Marketplace '{market_id}' fields must be an object.")
            return {}

        normalized_fields: dict[str, str] = {}
        for field_name, raw_value in raw_fields.items():
            if field_name not in AI_TEXT_FIELDS:
                errors.append(f"Field '{field_name}' is not allowlisted for AI drafts.")
                continue
            if raw_value is None:
                continue
            if not isinstance(raw_value, str):
                errors.append(f"Field '{field_name}' in marketplace '{market_id}' must be a string.")
                continue

            sanitized_value = self._sanitize_html(raw_value, allow_markup=field_name not in TITLE_FIELDS)
            if raw_value.strip() and not sanitized_value:
                errors.append(
                    f"Field '{field_name}' in marketplace '{market_id}' became empty after sanitation."
                )
                continue

            max_length = TEXT_FIELD_LIMITS[field_name]
            if len(sanitized_value) > max_length:
                errors.append(
                    f"Field '{field_name}' in marketplace '{market_id}' exceeds max length {max_length}."
                )
                continue

            if sanitized_value != raw_value.strip():
                warnings.append(
                    f"Field '{field_name}' in marketplace '{market_id}' was sanitized before persistence."
                )

            if sanitized_value:
                normalized_fields[field_name] = sanitized_value

        return normalized_fields

    def _normalize_features(
        self,
        *,
        market_id: str,
        raw_feature_values: Any,
        base_marketplace: Any,
        warnings: list[str],
        errors: list[str],
    ) -> dict[str, FeatureValue]:
        """Validate feature names and values against the allowed/current persisted schema."""
        if not isinstance(raw_feature_values, list):
            errors.append(f"Marketplace '{market_id}' feature_values must be an array.")
            return {}

        normalized_features: dict[str, FeatureValue] = {}
        seen_feature_names: set[str] = set()

        for raw_feature in raw_feature_values:
            if not isinstance(raw_feature, dict):
                errors.append(f"Marketplace '{market_id}' feature updates must be objects.")
                continue

            feature_name = str(raw_feature.get("name", "") or "").strip()
            if not feature_name:
                errors.append(f"Marketplace '{market_id}' contains a feature update without a name.")
                continue
            if feature_name in seen_feature_names:
                errors.append(f"Feature '{feature_name}' appears more than once for marketplace '{market_id}'.")
                continue
            seen_feature_names.add(feature_name)

            allowed_feature = base_marketplace.allowed_features.get(feature_name)
            current_feature = base_marketplace.current_features.get(feature_name)
            if allowed_feature is None and current_feature is None:
                errors.append(f"Feature '{feature_name}' is not present in the persisted schema for '{market_id}'.")
                continue

            raw_values = raw_feature.get("values") or []
            if not isinstance(raw_values, list):
                errors.append(f"Feature '{feature_name}' in marketplace '{market_id}' must use an array of values.")
                continue

            normalized_values = []
            for raw_value in raw_values:
                if not isinstance(raw_value, str):
                    errors.append(
                        f"Feature '{feature_name}' in marketplace '{market_id}' contains a non-string value."
                    )
                    continue
                normalized_value = " ".join(raw_value.split())
                if normalized_value and normalized_value not in normalized_values:
                    normalized_values.append(normalized_value)

            allowed_options = list(allowed_feature.options if allowed_feature else [])
            if allowed_options:
                invalid_values = [value for value in normalized_values if value not in allowed_options]
                if invalid_values:
                    errors.append(
                        f"Feature '{feature_name}' in marketplace '{market_id}' has invalid values: {invalid_values}."
                    )
                    continue
            elif normalized_values:
                warnings.append(
                    f"Feature '{feature_name}' in marketplace '{market_id}' has no allowed options in schema; values were kept as-is."
                )

            normalized_features[feature_name] = FeatureValue(
                name=feature_name,
                values=normalized_values,
                facet=bool((allowed_feature or current_feature).facet) if (allowed_feature or current_feature) else False,
                required=bool(allowed_feature.required) if allowed_feature else False,
                options=allowed_options,
            )

        return normalized_features

    def _build_diff_summary(self, *, aggregate: ProductAggregate, patch: ProductPatch) -> dict[str, Any]:
        """Build a compact change summary that future preview/save flows can reuse."""
        marketplaces_summary: dict[str, Any] = {}
        change_count = 0

        for market_id, marketplace_patch in patch.marketplace_patches.items():
            base_marketplace = aggregate.marketplaces.get(market_id)
            if base_marketplace is None:
                continue

            field_changes = []
            for field_name, next_value in marketplace_patch.fields.items():
                previous_value = str(base_marketplace.fields.get(field_name, "") or "")
                if previous_value == next_value:
                    continue
                field_changes.append(
                    {
                        "field": field_name,
                        "before": previous_value,
                        "after": next_value,
                    }
                )
                change_count += 1

            feature_changes = []
            for feature_name, next_feature in marketplace_patch.feature_values.items():
                previous_values = list(base_marketplace.current_features.get(feature_name, FeatureValue(name=feature_name)).values)
                if previous_values == list(next_feature.values):
                    continue
                feature_changes.append(
                    {
                        "feature": feature_name,
                        "before": previous_values,
                        "after": list(next_feature.values),
                    }
                )
                change_count += 1

            if field_changes or feature_changes:
                marketplaces_summary[market_id] = {
                    "field_changes": field_changes,
                    "feature_changes": feature_changes,
                }

        return {
            "change_count": change_count,
            "changed_marketplace_count": len(marketplaces_summary),
            "marketplaces": marketplaces_summary,
        }

    def _sanitize_html(self, value: str, *, allow_markup: bool) -> str:
        """Strip dangerous HTML and keep only minimal formatting tags for descriptions."""
        soup = BeautifulSoup(value.strip(), "html.parser")

        for tag in soup.find_all(("script", "style")):
            tag.decompose()

        for tag in soup.find_all(True):
            if not allow_markup:
                tag.unwrap()
                continue
            if tag.name not in ALLOWED_DESCRIPTION_TAGS:
                tag.unwrap()
                continue
            tag.attrs = {}

        if not allow_markup:
            return " ".join(soup.get_text(" ", strip=True).split())

        sanitized = str(soup)
        return "\n".join(line.strip() for line in sanitized.splitlines() if line.strip())
