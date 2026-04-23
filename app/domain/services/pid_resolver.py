from __future__ import annotations

import re

from app.domain.models import SearchProductCandidate


class PidResolver:
    """Choose the most likely product pid from search result candidates."""

    @staticmethod
    def resolve(article: str, candidates: list[SearchProductCandidate]) -> str:
        """Rank candidates for the given article and return the best pid."""
        if not candidates:
            raise RuntimeError("No pid candidates found in search HTML")

        normalized_article = article.strip().lower()
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -PidResolver._score_candidate(normalized_article, candidate),
                candidate.position,
                candidate.pid,
            ),
        )
        return ranked[0].pid

    @staticmethod
    def _score_candidate(article: str, candidate: SearchProductCandidate) -> int:
        """Score one candidate using exact and partial article matches plus pid-bearing URLs."""
        haystack = " ".join(
            part for part in (candidate.title, candidate.snippet, candidate.href) if part
        ).lower()
        if not haystack:
            return 0

        score = 0
        if article and article == candidate.title.strip().lower():
            score += 120

        if article and re.search(rf"(?<!\w){re.escape(article)}(?!\w)", haystack):
            score += 100
        elif article and article in haystack:
            score += 60

        if "pid=" in candidate.href.lower():
            score += 10

        return score
