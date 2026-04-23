from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from app.domain.models import SearchProductCandidate

HEX32_RE = re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE)
PID_IN_URL_RE = re.compile(r"[?&]pid=([a-f0-9]{32})", re.IGNORECASE)


class SearchHtmlParser:
    """Extract product search candidates from the raw HTML returned by FOKS."""

    @staticmethod
    def parse(search_html: str) -> list[SearchProductCandidate]:
        """Parse links and fallback pid tokens from the search page."""
        soup = BeautifulSoup(search_html, "html.parser")
        candidates: list[SearchProductCandidate] = []
        seen: set[str] = set()

        for position, anchor in enumerate(soup.find_all("a", href=True)):
            href = anchor.get("href", "")
            match = PID_IN_URL_RE.search(href)
            if not match:
                continue

            pid = match.group(1).lower()
            if pid in seen:
                continue

            context = SearchHtmlParser._get_context(anchor)
            title = " ".join(anchor.stripped_strings)
            # We keep a short surrounding snippet so PID resolution can score multiple matches more accurately.
            snippet = " ".join(context.stripped_strings)
            candidates.append(
                SearchProductCandidate(
                    pid=pid,
                    title=title,
                    snippet=snippet,
                    href=href,
                    position=position,
                )
            )
            seen.add(pid)

        for position, match in enumerate(HEX32_RE.finditer(search_html), start=len(candidates)):
            pid = match.group(0).lower()
            if pid in seen:
                continue

            start = max(0, match.start() - 250)
            end = min(len(search_html), match.end() + 250)
            snippet = re.sub(r"\s+", " ", search_html[start:end]).strip()
            candidates.append(
                SearchProductCandidate(
                    pid=pid,
                    snippet=snippet,
                    position=position,
                )
            )
            seen.add(pid)

        return candidates

    @staticmethod
    def _get_context(anchor: Tag) -> Tag:
        """Find a nearby wrapper element that best represents one search result item."""
        current: Tag = anchor
        for _ in range(4):
            parent = current.parent
            if not isinstance(parent, Tag):
                break

            # Search results often sit inside shallow card/table wrappers, so walking a few levels is enough.
            if parent.name in {"tr", "li", "article"}:
                return parent

            classes = set(parent.get("class", []))
            if classes.intersection({"product", "products-item", "item", "row"}):
                return parent

            current = parent

        return anchor
