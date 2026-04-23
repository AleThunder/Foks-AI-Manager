from __future__ import annotations

import json
from typing import Any

from app.domain.models import FeatureValue


class FeatureService:
    """Normalize marketplace features into arrays expected by the save payload."""

    @staticmethod
    def build_feature_arrays(
        filled_features_raw: Any,
        category_schema: list[dict[str, Any]] | None,
    ) -> tuple[list[str], list[str], list[str]]:
        """Convert raw feature data and schema flags into three parallel payload arrays."""
        normalized = FeatureService.normalize_filled_features(filled_features_raw)
        schema_facet_map = {
            (item.get("name") or "").strip(): str(bool(item.get("facet"))).lower()
            for item in (category_schema or [])
            if item.get("name")
        }

        feature_names: list[str] = []
        feature_values: list[str] = []
        feature_facets: list[str] = []

        for name, values in normalized.items():
            feature_names.append(name)
            feature_values.append(FeatureService._serialize_feature_values(values))
            feature_facets.append(schema_facet_map.get(name, "false"))

        return feature_names, feature_values, feature_facets

    @staticmethod
    def normalize_filled_features(raw: Any) -> dict[str, list[str]]:
        """Bring raw feature responses into a stable dict[name, list[value]] structure."""
        if raw is None:
            return {}

        if isinstance(raw, dict):
            result: dict[str, list[str]] = {}
            for key, value in raw.items():
                if isinstance(value, list):
                    result[str(key)] = [
                        FeatureService._value_to_string(item)
                        for item in value
                        if item is not None and str(item) != ""
                    ]
                elif value is None or str(value) == "":
                    result[str(key)] = []
                else:
                    result[str(key)] = [FeatureService._value_to_string(value)]
            return result

        if isinstance(raw, list):
            result: dict[str, list[str]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue

                name = item.get("name") or item.get("featureName") or item.get("title")
                if not name:
                    continue

                value = (
                    item.get("value")
                    or item.get("values")
                    or item.get("featureValue")
                    or item.get("selected")
                )

                if isinstance(value, list):
                    result[str(name)] = [
                        FeatureService._value_to_string(entry)
                        for entry in value
                        if entry is not None and str(entry) != ""
                    ]
                elif value is None or str(value) == "":
                    result[str(name)] = []
                else:
                    result[str(name)] = [FeatureService._value_to_string(value)]

            return result

        return {}

    @staticmethod
    def build_current_feature_map(raw: Any) -> dict[str, FeatureValue]:
        """Convert current product features into a name-indexed map of domain feature values."""
        normalized_features = FeatureService.normalize_filled_features(raw)
        raw_map = FeatureService._group_raw_features_by_name(raw)
        return {
            name: FeatureValue(
                name=name,
                values=list(values),
                raw=raw_map.get(name, {}),
            )
            for name, values in normalized_features.items()
        }

    @staticmethod
    def build_allowed_feature_map(
        category_schema: list[dict[str, Any]] | None,
    ) -> dict[str, FeatureValue]:
        """Normalize category schema entries into a name-indexed mapping for comparison and mapping."""
        allowed_features: dict[str, FeatureValue] = {}

        for item in category_schema or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            allowed_features[name] = FeatureValue(
                name=name,
                facet=bool(item.get("facet")),
                required=bool(item.get("required")),
                options=FeatureService._extract_option_values(item),
                raw=item,
            )

        return allowed_features

    @staticmethod
    def _serialize_feature_values(values: list[str]) -> str:
        """Serialize one feature's values into the string format accepted by FOKS."""
        if not values:
            return ""
        if len(values) == 1:
            return values[0]
        return "<br/>".join(values)

    @staticmethod
    def _extract_option_values(item: dict[str, Any]) -> list[str]:
        """Extract selectable values from a category schema entry in a tolerant way."""
        candidates = (
            item.get("options")
            or item.get("values")
            or item.get("featureValues")
            or item.get("items")
            or []
        )

        if not isinstance(candidates, list):
            return []

        options: list[str] = []
        for candidate in candidates:
            if isinstance(candidate, dict):
                value = candidate.get("value") or candidate.get("name") or candidate.get("title")
                if value is not None and str(value) != "":
                    options.append(str(value))
            elif candidate is not None and str(candidate) != "":
                options.append(str(candidate))

        return options

    @staticmethod
    def _group_raw_features_by_name(raw: Any) -> dict[str, dict[str, Any]]:
        """Index raw feature payload entries by name when the source format provides per-feature objects."""
        if not isinstance(raw, list):
            return {}

        raw_map: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue

            name = item.get("name") or item.get("featureName") or item.get("title")
            if name:
                raw_map[str(name)] = item

        return raw_map

    @staticmethod
    def _value_to_string(value: Any) -> str:
        """Convert arbitrary feature values into a string representation safe for payload output."""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
