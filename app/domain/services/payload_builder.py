from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.domain.models import ModalParseResult
from app.domain.services.feature_service import FeatureService


class SavePayloadBuilder:
    """Build the final save payload from a normalized modal and marketplace features."""

    DEFAULT_MIDS = [
        "allo",
        "dropfoks",
        "epicentr",
        "epicentr_ua",
        "eva",
        "fua",
        "hotline",
        "joom",
        "kasta",
        "prom",
        "rozetka",
        "rozetka_ua",
    ]

    FEATURE_MIDS = [
        "dropfoks",
        "epicentr",
        "epicentr_ua",
        "eva",
        "fua",
        "hotline",
        "joom",
        "kasta",
        "prom",
        "rozetka",
        "rozetka_ua",
    ]

    @classmethod
    def build(
        cls,
        modal: ModalParseResult,
        product_features: dict[str, Any],
        category_schemas: dict[str, list[dict[str, Any]] | None],
    ) -> dict[str, Any]:
        """Compose the payload fields required by the FOKS save endpoint."""
        # Start from the normalized modal view so payload generation no longer depends on raw HTML naming tricks.
        payload = deepcopy(modal.to_form_fields())
        cls._drop_noise(payload)
        payload["marketCatIds"] = cls._collect_marketplace_field(modal, "marketCatIds", cls.FEATURE_MIDS, "")
        payload["marketCatNames"] = cls._collect_marketplace_field(modal, "marketCatNames", cls.FEATURE_MIDS, "")
        payload["priceExt"] = cls._collect_marketplace_field(modal, "priceExt", cls.DEFAULT_MIDS, "")
        payload["oldPriceExt"] = cls._collect_marketplace_field(modal, "oldPriceExt", cls.DEFAULT_MIDS, "")
        payload["shippingPriceExt"] = cls._collect_marketplace_field(modal, "shippingPriceExt", ["joom"], "")
        payload["unloadExt"] = cls._collect_marketplace_field(modal, "unloadExt", cls.DEFAULT_MIDS, False)
        payload["nameExt"] = cls._collect_marketplace_field(modal, "nameExt", cls.DEFAULT_MIDS, "")
        payload["tagsExt"] = cls._collect_marketplace_field(modal, "tagsExt", ["joom"], "")
        payload["storeId"] = cls._collect_marketplace_field(modal, "storeId", ["joom"], "")

        feature_names: dict[str, list[str]] = {mid: [] for mid in cls.FEATURE_MIDS}
        feature_values: dict[str, list[str]] = {mid: [] for mid in cls.FEATURE_MIDS}
        feature_facets: dict[str, list[str]] = {mid: [] for mid in cls.FEATURE_MIDS}

        for mid in cls.FEATURE_MIDS:
            names, values, facets = FeatureService.build_feature_arrays(
                filled_features_raw=product_features.get(mid),
                category_schema=category_schemas.get(mid),
            )
            feature_names[mid] = names
            feature_values[mid] = values
            feature_facets[mid] = facets

        payload["featureNames"] = feature_names
        payload["featureValues"] = feature_values
        payload["featureFacets"] = feature_facets
        payload["extendedInfo"] = json.dumps(
            modal.extinfo_by_market,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload.setdefault("id", modal.product_id)
        payload.setdefault("offerId", modal.offer_id)

        return payload

    @staticmethod
    def _collect_marketplace_field(
        modal: ModalParseResult,
        field_name: str,
        defaults: list[str],
        default_value: Any,
    ) -> dict[str, Any]:
        """Collect one marketplace-scoped field with defaults for known marketplaces."""
        result: dict[str, Any] = {key: default_value for key in defaults}
        result.update(modal.get_marketplace_values(field_name))
        return result

    @staticmethod
    def _drop_noise(payload: dict[str, Any]) -> None:
        """Remove fields that should never be included in the final save payload."""
        noisy_keys = {"descriptionText"}
        for key in list(payload.keys()):
            if key in noisy_keys:
                payload.pop(key, None)
