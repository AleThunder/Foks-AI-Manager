from __future__ import annotations

from app.domain.services.pid_resolver import PidResolver
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.foks.search_parser import SearchHtmlParser
from app.infrastructure.logging import get_logger


class ProductSearchService:
    """Run the article search flow and resolve one stable pid from the results."""

    def __init__(self, session: FoksSession) -> None:
        """Bind the search service to an authenticated FOKS session."""
        self.session = session
        self._logger = get_logger("app.integration.foks.read")

    def search_product_html(self, article: str) -> str:
        """Fetch the raw search results HTML for the given article."""
        return self.session.get_html(
            "/c/products",
            params={
                "q": article,
                "price1": "",
                "price2": "",
                "l": "",
                "avail": "",
                "mstr": "",
                "v": "",
                "appr": "",
                "c": "",
            },
        )

    def extract_pid_from_search(self, search_html: str, article: str) -> str:
        """Parse search results and resolve the best pid candidate for one article."""
        candidates = SearchHtmlParser.parse(search_html)
        pid = PidResolver.resolve(article, candidates)
        self._logger.info(
            "product_pid_resolved",
            extra={
                "event": "product_pid_resolved",
                "article": article,
                "pid": pid,
                "candidate_count": len(candidates),
            },
        )
        return pid

    def find_pid_by_article(self, article: str) -> str:
        """Execute the full search-to-pid flow for one article."""
        self._logger.info(
            "product_search_started",
            extra={"event": "product_search_started", "article": article},
        )
        search_html = self.search_product_html(article)
        return self.extract_pid_from_search(search_html, article)
