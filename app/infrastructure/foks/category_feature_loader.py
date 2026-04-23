from __future__ import annotations

from typing import Any

from app.domain.models import FeatureValue
from app.domain.services.feature_service import FeatureService
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger


class CategoryFeatureLoader:
    """Load and prepare the category feature schema for one marketplace/category pair."""

    def __init__(self, session: FoksSession) -> None:
        """Bind the loader to a live FOKS session."""
        self.session = session
        self._logger = get_logger("app.integration.foks.read")

    def load(
        self,
        *,
        mid: str,
        market_category_id: str,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, FeatureValue]]:
        """Fetch the category schema and index allowed features by name for later mapping."""
        if not market_category_id:
            return None, {}

        schema_raw = self.session.get_json(
            "/api/v1/market-cat/features",
            params={"mid": mid, "mcid": market_category_id},
        )
        allowed_features = FeatureService.build_allowed_feature_map(schema_raw)
        self._logger.info(
            "category_features_loaded",
            extra={
                "event": "category_features_loaded",
                "market_id": mid,
                "market_category_id": market_category_id,
                "feature_count": len(allowed_features),
            },
        )
        return schema_raw, allowed_features
