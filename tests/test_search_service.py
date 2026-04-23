from __future__ import annotations

import unittest

from app.domain.services.pid_resolver import PidResolver
from app.infrastructure.foks.search_parser import SearchHtmlParser


class SearchServiceTests(unittest.TestCase):
    """Verify search parsing and pid resolution from product search HTML."""

    def test_parser_and_resolver_pick_best_pid_when_multiple_products_found(self) -> None:
        """Resolver should choose the candidate whose snippet matches the requested article."""
        article = "ART-777"
        html = """
        <html>
          <body>
            <div class="product">
              <a href="/c/products/productModal?pid=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">Wrong item</a>
              <span>ART-111</span>
            </div>
            <div class="product">
              <a href="/c/products/productModal?pid=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">Target item</a>
              <span>ART-777</span>
            </div>
          </body>
        </html>
        """

        candidates = SearchHtmlParser.parse(html)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            PidResolver.resolve(article, candidates),
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )

    def test_parser_falls_back_to_hex_candidates(self) -> None:
        """Parser should still recover hex-like pid candidates from sparse HTML."""
        html = "<div>Candidate cccccccccccccccccccccccccccccccc somewhere in html</div>"

        candidates = SearchHtmlParser.parse(html)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].pid, "cccccccccccccccccccccccccccccccc")


if __name__ == "__main__":
    unittest.main()
