from __future__ import annotations

import unittest

from app.infrastructure.foks.category_feature_loader import CategoryFeatureLoader
from app.infrastructure.foks.product_feature_loader import ProductFeatureLoader


class FakeSession:
    def get_json(self, path: str, params: dict[str, str] | None = None):
        if path.startswith("/api/v1/product/features/"):
            return [
                {"name": "Color", "values": ["Black"]},
                {"name": "Memory", "value": "128 GB"},
            ]
        if path == "/api/v1/market-cat/features":
            return [
                {"name": "Color", "facet": True, "required": True, "options": ["Black", "White"]},
                {"name": "Memory", "facet": False, "values": ["64 GB", "128 GB"]},
            ]
        raise AssertionError(path)


class FeatureLoaderTests(unittest.TestCase):
    def test_product_feature_loader_returns_raw_and_normalized_features(self) -> None:
        loader = ProductFeatureLoader(session=FakeSession())

        raw_features, normalized_features = loader.load(product_id="prod-1", mid="prom")

        self.assertEqual(len(raw_features), 2)
        self.assertEqual(normalized_features["Color"].values, ["Black"])
        self.assertEqual(normalized_features["Memory"].values, ["128 GB"])

    def test_category_feature_loader_returns_schema_and_allowed_feature_map(self) -> None:
        loader = CategoryFeatureLoader(session=FakeSession())

        schema_raw, allowed_features = loader.load(mid="prom", market_category_id="cat-1")

        self.assertEqual(len(schema_raw or []), 2)
        self.assertEqual(allowed_features["Color"].name, "Color")
        self.assertTrue(allowed_features["Color"].facet)
        self.assertTrue(allowed_features["Color"].required)
        self.assertEqual(allowed_features["Memory"].options, ["64 GB", "128 GB"])


if __name__ == "__main__":
    unittest.main()
