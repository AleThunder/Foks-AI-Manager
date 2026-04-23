from __future__ import annotations

from typing import Any

from app.application.ports import SnapshotRepositoryPort, TaskRepositoryPort
from app.application.services.product_read import GetProductByArticleService
from app.domain.services.payload_builder import SavePayloadBuilder
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger, get_task_id


class BuildSavePayloadService:
    """Convert a product snapshot into the final save request expected by FOKS."""

    def __init__(
        self,
        *,
        snapshot_repository: SnapshotRepositoryPort,
        task_repository: TaskRepositoryPort,
        session_factory: type[FoksSession] = FoksSession,
    ) -> None:
        """Prepare collaborators needed for read and payload build orchestration."""
        self._session_factory = session_factory
        self._read_service = GetProductByArticleService(
            snapshot_repository=snapshot_repository,
            task_repository=task_repository,
            session_factory=session_factory,
        )
        self._save_logger = get_logger("app.integration.foks.save")
        self._task_repository = task_repository

    def build_save_payload(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        article: str,
        mids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Read product data by article and assemble the final save payload structure."""
        task_record_id = self._task_repository.start_task(
            task_id=get_task_id(),
            task_type="build_save_payload",
            article=article,
        )
        try:
            snapshot = self._read_service.get_product_by_article(
                base_url=base_url,
                username=username,
                password=password,
                article=article,
                mids=mids,
            )
            session = self._session_factory(
                base_url=base_url,
                username=username,
                password=password,
            )

            product_features: dict[str, Any] = {
                market_id: result.raw_product_features
                for market_id, result in snapshot.marketplaces.items()
            }
            category_schemas: dict[str, list[dict[str, Any]] | None] = {
                market_id: result.raw_category_features
                for market_id, result in snapshot.marketplaces.items()
            }

            payload = SavePayloadBuilder.build(
                modal=snapshot.to_modal_parse_result(),
                product_features=product_features,
                category_schemas=category_schemas,
            )
            save_request = {
                "url": "/c/products/save",
                "headers": session.build_json_headers(csrf_token=snapshot.csrf_save_token),
                "payload": payload,
            }
            self._task_repository.complete_task(
                task_record_id,
                pid=snapshot.pid,
                details={"marketplace_count": len(snapshot.marketplaces)},
            )
            self._save_logger.info(
                "save_payload_built",
                extra={
                    "event": "save_payload_built",
                    "article": article,
                    "pid": snapshot.pid,
                    "marketplace_count": len(snapshot.marketplaces),
                },
            )
            return save_request
        except Exception as exc:
            self._task_repository.fail_task(
                task_record_id,
                error_message=str(exc),
                details={"article": article},
            )
            raise
