from __future__ import annotations

from functools import lru_cache

from app.infrastructure.db import PatchRepository, ProductAggregateRepository, ProductRepository, SnapshotRepository, TaskRepository
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.application.services.product_ai import ProductAIContextBuilderService
from app.application.services.product_payload import BuildSavePayloadService
from app.application.services.product_patch_validation import ProductPatchValidationService
from app.application.services.product_preview import PreviewProductPatchService
from app.application.services.product_save import ApplyProductPatchService, SaveProductPatchService
from app.infrastructure.ai import OpenAIProductPatchGateway
from app.infrastructure.settings import Settings, get_settings


@lru_cache(maxsize=1)
def get_payload_service() -> BuildSavePayloadService:
    """Return a cached payload builder service instance for API handlers."""
    return BuildSavePayloadService(
        snapshot_repository=SnapshotRepository(),
        task_repository=TaskRepository(),
    )


@lru_cache(maxsize=1)
def get_product_aggregate_service() -> GetProductAggregateService:
    """Return a cached service that reads persisted product aggregates from the database."""
    product_repository = ProductRepository()
    snapshot_repository = SnapshotRepository(product_repository=product_repository)
    return GetProductAggregateService(
        aggregate_repository=ProductAggregateRepository(
            product_repository=product_repository,
            snapshot_repository=snapshot_repository,
        )
    )


@lru_cache(maxsize=1)
def get_product_refresh_service() -> RefreshProductAggregateService:
    """Return a cached service that refreshes one product from FOKS and reads back the aggregate."""
    product_repository = ProductRepository()
    snapshot_repository = SnapshotRepository(product_repository=product_repository)
    return RefreshProductAggregateService(
        snapshot_repository=snapshot_repository,
        task_repository=TaskRepository(),
        aggregate_repository=ProductAggregateRepository(
            product_repository=product_repository,
            snapshot_repository=snapshot_repository,
        ),
    )


@lru_cache(maxsize=1)
def get_preview_patch_service() -> PreviewProductPatchService:
    """Return a cached service that generates/validates persisted draft patches."""
    settings = get_settings()
    product_repository = ProductRepository()
    snapshot_repository = SnapshotRepository(product_repository=product_repository)
    aggregate_service = GetProductAggregateService(
        aggregate_repository=ProductAggregateRepository(
            product_repository=product_repository,
            snapshot_repository=snapshot_repository,
        )
    )
    patch_generator = (
        OpenAIProductPatchGateway(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.openai_timeout_seconds,
        )
        if settings.openai_api_key
        else None
    )
    return PreviewProductPatchService(
        aggregate_service=aggregate_service,
        patch_repository=PatchRepository(),
        task_repository=TaskRepository(),
        ai_context_builder=ProductAIContextBuilderService(),
        patch_validator=ProductPatchValidationService(),
        patch_generator=patch_generator,
    )


@lru_cache(maxsize=1)
def get_save_patch_service() -> SaveProductPatchService:
    """Return a cached service that applies, saves, and verifies persisted draft patches."""
    product_repository = ProductRepository()
    snapshot_repository = SnapshotRepository(product_repository=product_repository)
    aggregate_repository = ProductAggregateRepository(
        product_repository=product_repository,
        snapshot_repository=snapshot_repository,
    )
    aggregate_service = GetProductAggregateService(aggregate_repository=aggregate_repository)
    refresh_service = RefreshProductAggregateService(
        snapshot_repository=snapshot_repository,
        task_repository=TaskRepository(),
        aggregate_repository=aggregate_repository,
    )
    return SaveProductPatchService(
        aggregate_service=aggregate_service,
        refresh_service=refresh_service,
        snapshot_repository=snapshot_repository,
        patch_repository=PatchRepository(),
        task_repository=TaskRepository(),
        apply_patch_service=ApplyProductPatchService(),
    )


def get_runtime_settings() -> Settings:
    """Expose application settings through FastAPI dependency injection."""
    return get_settings()
