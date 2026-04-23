from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.infrastructure.foks.modal_parser import ModalParser


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MODAL_FIXTURE_PATH = FIXTURES_DIR / "FoksProductModal.txt"
SAVE_FIXTURE_PATH = FIXTURES_DIR / "FoksProductSave.txt"


class ReadFixtureRegressionTests(unittest.TestCase):
    """Protect modal parsing against regressions using real FOKS fixtures."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the real modal and save payload fixtures once for the whole test class."""
        cls.modal_html = MODAL_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.save_payload = json.loads(SAVE_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.parsed_modal = ModalParser.parse(cls.modal_html)

    def test_modal_fixture_is_parsed_into_expected_identity_fields(self) -> None:
        """Ensure critical identity fields still parse correctly from the real modal HTML."""
        self.assertEqual(self.parsed_modal.product_id, self.save_payload["id"])
        self.assertEqual(self.parsed_modal.offer_id, self.save_payload["offerId"])
        self.assertEqual(self.parsed_modal.basic_fields["name"], self.save_payload["name"])
        self.assertEqual(self.parsed_modal.basic_fields["article"], self.save_payload["article"])
        self.assertTrue(self.parsed_modal.csrf_save_token)

    def test_modal_fixture_preserves_flags_and_marketplace_mappings(self) -> None:
        """Verify real checkbox flags and marketplace fields remain aligned with the saved payload."""
        self.assertEqual(self.parsed_modal.flags["approved"], self.save_payload["approved"])
        self.assertEqual(self.parsed_modal.flags["availGuaranteed"], self.save_payload["availGuaranteed"])
        self.assertEqual(self.parsed_modal.flags["epicRuForOrder"], self.save_payload["epicRuForOrder"])
        self.assertEqual(self.parsed_modal.flags["epicUaForOrder"], self.save_payload["epicUaForOrder"])
        self.assertEqual(self.parsed_modal.market_cat_ids["prom"], self.save_payload["marketCatIds"]["prom"])
        self.assertEqual(self.parsed_modal.market_cat_ids["rozetka"], self.save_payload["marketCatIds"]["rozetka"])
        self.assertEqual(self.parsed_modal.marketplace_fields["prom"]["priceExt"], self.save_payload["priceExt"]["prom"])
        self.assertEqual(self.parsed_modal.marketplace_fields["prom"]["nameExt"], self.save_payload["nameExt"]["prom"])
        self.assertEqual(self.parsed_modal.marketplace_fields["rozetka"]["nameExt"], self.save_payload["nameExt"]["rozetka"])

    def test_modal_fixture_extended_info_matches_saved_payload(self) -> None:
        """Ensure the extinfo payload serialized for save still matches what is parsed from the modal."""
        saved_extended_info = json.loads(self.save_payload["extendedInfo"])
        common_market_ids = sorted(set(self.parsed_modal.extinfo_by_market) & set(saved_extended_info))

        self.assertIn("prom", common_market_ids)
        self.assertIn("rozetka", common_market_ids)
        self.assertIn("epicentr_ua", common_market_ids)
        for market_id in common_market_ids:
            self.assertEqual(
                self.parsed_modal.extinfo_by_market[market_id],
                saved_extended_info[market_id],
            )
        self.assertIn("prom", self.parsed_modal.marketplaces_meta)
        self.assertIn("rozetka", self.parsed_modal.marketplaces_meta)
        self.assertIn("epicentr", self.parsed_modal.marketplaces_meta)


if __name__ == "__main__":
    unittest.main()
