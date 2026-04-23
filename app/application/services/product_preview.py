from __future__ import annotations

from typing import Any

from app.application.ports import PatchRepositoryPort, ProductPatchGeneratorPort, TaskRepositoryPort
from app.application.services.product_aggregate import GetProductAggregateService
from app.application.services.product_ai import ProductAIContextBuilderService
from app.application.services.product_patch_validation import ProductPatchValidationService
from app.application.services.prompts import PRODUCT_PATCH_DEFAULT_INSTRUCTIONS
from app.domain.models import PersistedProductPatch
from app.infrastructure.logging import get_task_id


class PreviewProductPatchService:
    """Generate or validate a normalized draft patch, persist it, and expose lifecycle metadata."""

    def __init__(
        self,
        *,
        aggregate_service: GetProductAggregateService,
        patch_repository: PatchRepositoryPort,
        task_repository: TaskRepositoryPort,
        ai_context_builder: ProductAIContextBuilderService | None = None,
        patch_validator: ProductPatchValidationService | None = None,
        patch_generator: ProductPatchGeneratorPort | None = None,
    ) -> None:
        """Prepare collaborators needed for previewing normalized patch drafts."""
        self._aggregate_service = aggregate_service
        self._patch_repository = patch_repository
        self._task_repository = task_repository
        self._ai_context_builder = ai_context_builder or ProductAIContextBuilderService()
        self._patch_validator = patch_validator or ProductPatchValidationService()
        self._patch_generator = patch_generator

    def preview(
        self,
        *,
        article: str | None = None,
        product_id: int | None = None,
        instructions: str | None = None,
        raw_draft: dict[str, Any] | None = None,
    ) -> PersistedProductPatch:
        """Create a previewable persisted draft either from AI or from a manual normalized patch."""
        if article is None and product_id is None:
            raise ValueError("Either article or product_id must be provided.")

        aggregate = (
            self._aggregate_service.get_by_article(article=article)
            if article is not None
            else self._aggregate_service.get_by_id(product_id=product_id or 0)
        )
        if aggregate is None or aggregate.latest_snapshot is None:
            identifier = article if article is not None else str(product_id)
            raise LookupError(f"Persisted aggregate '{identifier}' was not found.")

        task_record_id = self._task_repository.start_task(
            task_id=get_task_id(),
            task_type="preview_patch",
            article=aggregate.identity.article,
            pid=aggregate.identity.pid,
            details={
                "source": "manual" if raw_draft is not None else "ai",
                "base_snapshot_id": aggregate.latest_snapshot.id,
            },
        )

        try:
            resolved_raw_draft = raw_draft
            if resolved_raw_draft is None:
                if self._patch_generator is None:
                    raise RuntimeError("AI patch generator is not configured.")
                context = self._ai_context_builder.build_from_aggregate(aggregate)
                resolved_raw_draft = self._patch_generator.generate_patch(
                    context=context,
                    instructions=instructions or PRODUCT_PATCH_DEFAULT_INSTRUCTIONS,
                )

            validation = self._patch_validator.validate(
                aggregate=aggregate,
                raw_patch=resolved_raw_draft,
            )
            status = "failed" if validation.errors else "draft"
            patch_id = self._patch_repository.save_patch(
                product_record_id=aggregate.identity.id,
                patch=validation.patch,
                article=aggregate.identity.article,
                pid=aggregate.identity.pid,
                base_snapshot_id=aggregate.latest_snapshot.id,
                status=status,
                save_url="",
                headers={},
                payload={},
                validation_warnings=validation.warnings,
                validation_errors=validation.errors,
                diff_summary=validation.diff_summary,
                task_record_id=task_record_id,
            )
            persisted_patch = self._patch_repository.get_patch_by_id(patch_id)
            assert persisted_patch is not None

            if validation.errors:
                self._task_repository.fail_task(
                    task_record_id,
                    error_message="Patch validation failed",
                    details={
                        "patch_id": patch_id,
                        "validation_error_count": len(validation.errors),
                        "validation_warning_count": len(validation.warnings),
                    },
                )
                return persisted_patch

            self._task_repository.complete_task(
                task_record_id,
                product_record_id=aggregate.identity.id,
                pid=aggregate.identity.pid,
                details={
                    "patch_id": patch_id,
                    "validation_warning_count": len(validation.warnings),
                    "change_count": validation.diff_summary.get("change_count", 0),
                },
            )
            return persisted_patch
        except Exception as exc:
            self._task_repository.fail_task(
                task_record_id,
                error_message=str(exc),
                details={"article": aggregate.identity.article},
            )
            raise
