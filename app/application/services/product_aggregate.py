from __future__ import annotations

from app.application.ports import ProductAggregateRepositoryPort, SnapshotRepositoryPort, TaskRepositoryPort
from app.application.services.product_read import GetProductByArticleService
from app.domain.models import ProductAggregate
from app.infrastructure.foks.session import FoksSession


class GetProductAggregateService:
    """Load persisted product aggregates for public API reads without side effects."""

    def __init__(self, *, aggregate_repository: ProductAggregateRepositoryPort) -> None:
        """Store the repository that knows how to compose the persisted aggregate."""
        self._aggregate_repository = aggregate_repository

    def get_by_article(self, *, article: str) -> ProductAggregate | None:
        """Return the latest aggregate for one article from the local database."""
        return self._aggregate_repository.get_latest_aggregate_by_article(article)

    def get_by_id(self, *, product_id: int) -> ProductAggregate | None:
        """Return the latest aggregate for one internal product identifier."""
        return self._aggregate_repository.get_latest_aggregate_by_id(product_id)


class RefreshProductAggregateService:
    """Refresh a product from FOKS, persist the snapshot, and return the aggregate read model."""

    def __init__(
        self,
        *,
        snapshot_repository: SnapshotRepositoryPort,
        task_repository: TaskRepositoryPort,
        aggregate_repository: ProductAggregateRepositoryPort,
        session_factory: type[FoksSession] = FoksSession,
    ) -> None:
        """Prepare the collaborators needed for refresh and aggregate loading."""
        self._aggregate_repository = aggregate_repository
        self._read_service = GetProductByArticleService(
            snapshot_repository=snapshot_repository,
            task_repository=task_repository,
            session_factory=session_factory,
        )

    def refresh(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        article: str,
        mids: list[str] | None = None,
    ) -> ProductAggregate:
        """Execute a live FOKS read, persist the snapshot, then return the latest aggregate."""
        self._read_service.get_product_by_article(
            base_url=base_url,
            username=username,
            password=password,
            article=article,
            mids=mids,
        )
        aggregate = self._aggregate_repository.get_latest_aggregate_by_article(article)
        if aggregate is None:
            raise LookupError(f"Persisted aggregate for article '{article}' was not found after refresh.")
        return aggregate
