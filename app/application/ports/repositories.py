from __future__ import annotations

from typing import Any, Protocol

from datetime import datetime

from app.domain.models import PersistedProductPatch, ProductAggregate, ProductPatch, ProductSnapshot


class ProductRepositoryPort(Protocol):
    """Describe product identity operations required by the application layer."""

    def get_record_id_by_pid(self, pid: str) -> int | None:
        """Resolve the stored database identifier for one product pid."""


class SnapshotRepositoryPort(Protocol):
    """Describe snapshot persistence operations required by the read flow."""

    def save_snapshot(
        self,
        snapshot: ProductSnapshot,
        *,
        raw_modal_html: str = "",
        task_record_id: int | None = None,
    ) -> tuple[int, ProductSnapshot]:
        """Persist one normalized product snapshot and return its stored representation."""


class PatchRepositoryPort(Protocol):
    """Describe patch persistence operations required by the save flow."""

    def save_patch(
        self,
        *,
        product_record_id: int,
        patch: ProductPatch,
        article: str,
        pid: str,
        base_snapshot_id: int | None = None,
        status: str = "built",
        save_url: str,
        headers: dict[str, Any],
        payload: dict[str, Any],
        validation_warnings: list[str] | None = None,
        validation_errors: list[str] | None = None,
        diff_summary: dict[str, Any] | None = None,
        approved_at: datetime | None = None,
        approved_by: str | None = None,
        save_result: dict[str, Any] | None = None,
        task_record_id: int | None = None,
    ) -> int:
        """Persist one generated patch and return its database identifier."""

    def get_patch_by_id(self, patch_id: int) -> PersistedProductPatch | None:
        """Load one persisted patch together with its lifecycle metadata."""


class ProductAggregateRepositoryPort(Protocol):
    """Describe persisted aggregate read operations required by API-facing services."""

    def get_latest_aggregate_by_article(self, article: str) -> ProductAggregate | None:
        """Load the latest stored aggregate for one article without calling FOKS."""

    def get_latest_aggregate_by_id(self, product_record_id: int) -> ProductAggregate | None:
        """Load the latest stored aggregate for one internal database product id."""


class TaskRepositoryPort(Protocol):
    """Describe task persistence operations required by the orchestrating services."""

    def start_task(
        self,
        *,
        task_id: str,
        task_type: str,
        article: str | None = None,
        pid: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Create a task entry in running state and return its database identifier."""

    def complete_task(
        self,
        task_record_id: int,
        *,
        product_record_id: int | None = None,
        pid: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Mark a task as completed and store its final metadata."""

    def fail_task(
        self,
        task_record_id: int,
        *,
        error_message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Mark a task as failed and store the error details."""
