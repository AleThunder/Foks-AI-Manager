from __future__ import annotations

import unittest

from app.infrastructure.foks.modal_parser import ModalParser


class ModalParserTests(unittest.TestCase):
    """Validate modal parsing into normalized top-level and marketplace fields."""

    def test_modal_parser_splits_basic_fields_marketplace_fields_and_flags(self) -> None:
        """Modal parsing should separate product fields, flags, metadata, and marketplace values."""
        html = """
        <form id="productForm">
          <input name="id" value="prod-1" />
          <input name="offerId" value="offer-1" />
          <input name="name" value="Demo product" />
          <textarea name="descriptionText">demo description</textarea>
          <input type="checkbox" name="published" checked />
          <input name="marketCatIds['prom']" value="cat-1" />
          <input name="marketCatNames['prom']" value="Category 1" />
          <input name="priceExt['prom']" value="100" />
          <input name="unloadExt['prom']" value="true" />
          <prod-features marketid="prom" catid="cat-1" custcatid="custom-1"></prod-features>
          <prod-markup-info :extinfo='{"prom":{"foo":"bar"}}'></prod-markup-info>
          <script>
            saveProduct('save', 'X-CSRF-TOKEN', 'csrf-123')
          </script>
        </form>
        """

        result = ModalParser.parse(html)

        self.assertEqual(result.product_id, "prod-1")
        self.assertEqual(result.offer_id, "offer-1")
        self.assertEqual(result.csrf_save_token, "csrf-123")
        self.assertEqual(result.basic_fields["name"], "Demo product")
        self.assertEqual(result.flags["published"], True)
        self.assertEqual(result.marketplace_fields["prom"]["priceExt"], "100")
        self.assertEqual(result.marketplace_fields["prom"]["marketCatIds"], "cat-1")
        self.assertEqual(result.market_cat_names["prom"], "Category 1")
        self.assertEqual(result.marketplaces_meta["prom"].custcatid, "custom-1")
        self.assertEqual(result.extinfo_by_market["prom"]["foo"], "bar")
        self.assertEqual(result.to_form_fields()["priceExt['prom']"], "100")


if __name__ == "__main__":
    unittest.main()
