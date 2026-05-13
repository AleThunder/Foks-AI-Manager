from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.application.ports import PatchRepositoryPort, SnapshotRepositoryPort, TaskRepositoryPort
from app.application.services.product_aggregate import GetProductAggregateService
from app.application.services.product_save import ApplyProductPatchService
from app.domain.models import PersistedProductPatch
from app.infrastructure.foks.session import FoksSession
from app.infrastructure.logging import get_logger, get_task_id


SAVE_URL = "/c/products/save"


class PrepareSavePayloadService:
    """Prepare and persist the final FOKS save payload for a reviewed patch."""

    RETRYABLE_PATCH_STATUSES = {"draft", "approved", "verification_failed"}

    def __init__(
        self,
        *,
        aggregate_service: GetProductAggregateService,
        snapshot_repository: SnapshotRepositoryPort,
        patch_repository: PatchRepositoryPort,
        task_repository: TaskRepositoryPort,
        apply_patch_service: ApplyProductPatchService | None = None,
        session_factory: type[FoksSession] = FoksSession,
    ) -> None:
        """Store collaborators needed to build a final payload without posting to FOKS."""
        self._aggregate_service = aggregate_service
        self._snapshot_repository = snapshot_repository
        self._patch_repository = patch_repository
        self._task_repository = task_repository
        self._apply_patch_service = apply_patch_service or ApplyProductPatchService()
        self._session_factory = session_factory
        self._save_logger = get_logger("app.integration.foks.save")

    def prepare(
        self,
        *,
        patch_id: int,
        base_url: str,
        approved_by: str = "",
    ) -> dict[str, Any]:
        """Build, persist, and return the final save request for one validated patch."""
        persisted_patch = self._patch_repository.get_patch_by_id(patch_id)
        if persisted_patch is None:
            raise LookupError(f"Persisted patch '{patch_id}' was not found.")
        if persisted_patch.status not in self.RETRYABLE_PATCH_STATUSES:
            raise ValueError("Only draft, approved, or verification_failed patches can be prepared for save.")
        if persisted_patch.validation_errors:
            raise ValueError("Patch contains validation errors and cannot be prepared for save.")
        if persisted_patch.base_snapshot_id is None:
            raise ValueError("Patch is missing base_snapshot_id and cannot be prepared safely.")

        aggregate = self._aggregate_service.get_by_id(product_id=persisted_patch.product_record_id)
        if aggregate is None or aggregate.latest_snapshot is None:
            raise LookupError(f"Persisted aggregate for patch '{patch_id}' was not found.")
        if aggregate.latest_snapshot.id != persisted_patch.base_snapshot_id:
            raise ValueError(
                "Patch was generated from a stale snapshot. Refresh the product and generate a new preview."
            )

        task_record_id = self._task_repository.start_task(
            task_id=get_task_id(),
            task_type="prepare_save_payload",
            article=persisted_patch.article,
            pid=persisted_patch.pid,
            details={
                "patch_id": patch_id,
                "base_snapshot_id": persisted_patch.base_snapshot_id,
            },
        )

        try:
            base_snapshot = self._snapshot_repository.get_snapshot_by_id(persisted_patch.base_snapshot_id)
            if base_snapshot is None:
                raise LookupError(f"Base snapshot '{persisted_patch.base_snapshot_id}' was not found.")

            patched_snapshot = self._apply_patch_service.apply(
                snapshot=base_snapshot,
                patch=persisted_patch.patch,
            )
            payload = self._apply_patch_service.build_save_payload(snapshot=patched_snapshot)
            session = self._session_factory(base_url=base_url, username="", password="")
            headers = session.build_json_headers(csrf_token=patched_snapshot.csrf_save_token)

            resolved_approved_at = persisted_patch.approved_at or datetime.now(timezone.utc)
            resolved_approved_by = persisted_patch.approved_by or approved_by
            updated_patch = self._patch_repository.update_patch(
                patch_id,
                status="approved",
                approved_at=resolved_approved_at,
                approved_by=resolved_approved_by,
                save_url=SAVE_URL,
                headers=headers,
                payload=payload,
                task_record_id=task_record_id,
                save_result={
                    "pre_save_snapshot_id": persisted_patch.base_snapshot_id,
                    "audit": self._build_audit(
                        persisted_patch=persisted_patch,
                        approved_by=resolved_approved_by,
                    ),
                    "verification": {"status": "pending"},
                },
            )
            self._task_repository.complete_task(
                task_record_id,
                product_record_id=persisted_patch.product_record_id,
                pid=persisted_patch.pid,
                details={
                    "patch_id": patch_id,
                    "payload_key_count": len(payload),
                },
            )
            self._save_logger.info(
                "save_payload_prepared",
                extra={
                    "event": "save_payload_prepared",
                    "article": persisted_patch.article,
                    "pid": persisted_patch.pid,
                    "patch_id": patch_id,
                    "payload_key_count": len(payload),
                },
            )
            assert updated_patch is not None
            return {
                "save_request": {
                    "url": SAVE_URL,
                    "headers": headers,
                    "payload": payload,
                },
                "patch": updated_patch,
            }
        except Exception as exc:
            self._task_repository.fail_task(
                task_record_id,
                error_message=str(exc),
                details={"patch_id": patch_id},
            )
            raise

    def _build_audit(
        self,
        *,
        persisted_patch: PersistedProductPatch,
        approved_by: str,
    ) -> dict[str, Any]:
        """Build a compact audit record for a prepared but not-yet-posted save request."""
        return {
            "patch_id": persisted_patch.patch_id,
            "product_record_id": persisted_patch.product_record_id,
            "article": persisted_patch.article,
            "pid": persisted_patch.pid,
            "created_by": persisted_patch.created_by,
            "approved_by": approved_by,
            "base_snapshot_id": persisted_patch.base_snapshot_id,
            "post_save_snapshot_id": None,
            "diff_summary": persisted_patch.diff_summary,
        }
