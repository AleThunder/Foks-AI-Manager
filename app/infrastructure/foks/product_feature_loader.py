from __future__ import annotations

from typing import Any

from app.domain.models import FeatureValue
from app.domain.services.feature_service import FeatureService
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger


class ProductFeatureLoader:
    """Load and normalize current product features for one marketplace."""

    def __init__(self, session: FoksSession) -> None:
        """Bind the loader to a live FOKS session."""
        self.session = session
        self._logger = get_logger("app.integration.foks.read")

    def load(self, *, product_id: str, mid: str) -> tuple[Any, dict[str, FeatureValue]]:
        """Fetch product features from FOKS and normalize them for upper-layer comparisons."""
        raw_features = self.session.get_json(
            f"/api/v1/product/features/{product_id}",
            params={"mid": mid},
        )
        current_features = FeatureService.build_current_feature_map(raw_features)
        self._logger.info(
            "product_features_loaded",
            extra={
                "event": "product_features_loaded",
                "product_id": product_id,
                "market_id": mid,
                "feature_count": len(current_features),
            },
        )
        return raw_features, current_features
