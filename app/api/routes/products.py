from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_patch_repository,
    get_payload_service,
    get_preview_patch_service,
    get_product_aggregate_service,
    get_product_refresh_service,
    get_runtime_settings,
    get_save_patch_service,
)
from app.api.schemas import (
    PersistedProductPatchEnvelope,
    PersistedProductPatchResponse,
    PrepareSavePayloadRequest,
    PrepareSavePayloadResponse,
    ProductPatchChangesEnvelope,
    ProductPatchChangesResponse,
    PreviewPatchRequest,
    ProductAggregateEnvelope,
    ProductAggregateResponse,
    RefreshProductRequest,
    SavePatchRequest,
)
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.application.services.product_payload import PrepareSavePayloadService
from app.application.services.product_preview import PreviewProductPatchService
from app.application.services.product_save import SaveProductPatchService
from app.infrastructure.db import PatchRepository
from app.infrastructure.settings import Settings

router = APIRouter(prefix="/products", tags=["products"])


def _resolve_foks_credentials(
    *,
    base_url: str | None,
    username: str | None,
    password: str | None,
    settings: Settings,
) -> tuple[str, str, str]:
    """Resolve FOKS connection inputs from the request body or runtime settings."""
    resolved_base_url = base_url or settings.foks_base_url
    resolved_username = username or settings.foks_username
    resolved_password = password or settings.foks_password

    if not resolved_username or not resolved_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set FOKS_USERNAME and FOKS_PASSWORD in .env or pass them in the request body.",
        )

    return resolved_base_url, resolved_username, resolved_password


@router.post("/refresh", response_model=ProductAggregateEnvelope)
def refresh_product(
    request: RefreshProductRequest,
    service: RefreshProductAggregateService = Depends(get_product_refresh_service),
    settings: Settings = Depends(get_runtime_settings),
) -> ProductAggregateEnvelope:
    """Refresh one product from FOKS, persist a new snapshot, and return the latest aggregate."""
    base_url, username, password = _resolve_foks_credentials(
        base_url=request.base_url,
        username=request.username,
        password=request.password,
        settings=settings,
    )

    aggregate = service.refresh(
        base_url=base_url,
        username=username,
        password=password,
        article=request.article,
        mids=request.mids,
    )
    return ProductAggregateEnvelope(data=ProductAggregateResponse.from_domain(aggregate))


@router.get("/by-article", response_model=ProductAggregateEnvelope)
def get_product_by_article(
    article: str,
    service: GetProductAggregateService = Depends(get_product_aggregate_service),
) -> ProductAggregateEnvelope:
    """Return the latest persisted aggregate for one article without contacting FOKS."""
    aggregate = service.get_by_article(article=article)
    if aggregate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with article '{article}' was not found.",
        )
    return ProductAggregateEnvelope(data=ProductAggregateResponse.from_domain(aggregate))


@router.post("/save-payload", response_model=PrepareSavePayloadResponse)
def prepare_save_payload(
    request: PrepareSavePayloadRequest,
    service: PrepareSavePayloadService = Depends(get_payload_service),
    settings: Settings = Depends(get_runtime_settings),
) -> PrepareSavePayloadResponse:
    """Prepare the final save payload for a reviewed persisted patch without posting to FOKS."""
    try:
        result = service.prepare(
            patch_id=request.patch_id,
            base_url=request.base_url or settings.foks_base_url,
            approved_by=request.approved_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return PrepareSavePayloadResponse(
        data={
            "save_request": result["save_request"],
            "patch": PersistedProductPatchResponse.from_domain(result["patch"]).model_dump(mode="json"),
        }
    )


@router.post("/preview-patch", response_model=PersistedProductPatchEnvelope)
def preview_patch(
    request: PreviewPatchRequest,
    service: PreviewProductPatchService = Depends(get_preview_patch_service),
) -> PersistedProductPatchEnvelope:
    """Generate or validate a normalized draft patch and persist its lifecycle state."""
    try:
        persisted_patch = service.preview(
            article=request.article,
            product_id=request.product_id,
            mids=request.mids,
            created_by=request.created_by,
            instructions=request.instructions,
            raw_draft=request.draft.model_dump(mode="json") if request.draft else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return PersistedProductPatchEnvelope(
        data=PersistedProductPatchResponse.from_domain(persisted_patch)
    )


@router.post("/save", response_model=PersistedProductPatchEnvelope)
def save_patch(
    request: SavePatchRequest,
    service: SaveProductPatchService = Depends(get_save_patch_service),
    settings: Settings = Depends(get_runtime_settings),
) -> PersistedProductPatchEnvelope:
    """Approve one persisted draft patch, save it to FOKS, and return the final lifecycle state."""
    base_url, username, password = _resolve_foks_credentials(
        base_url=request.base_url,
        username=request.username,
        password=request.password,
        settings=settings,
    )

    try:
        persisted_patch = service.save(
            patch_id=request.patch_id,
            base_url=base_url,
            username=username,
            password=password,
            approved_by=request.approved_by,
            mids=request.mids,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return PersistedProductPatchEnvelope(data=PersistedProductPatchResponse.from_domain(persisted_patch))


@router.get("/patches/{patch_id}/changes", response_model=ProductPatchChangesEnvelope)
def get_patch_changes(
    patch_id: int,
    patch_repository: PatchRepository = Depends(get_patch_repository),
) -> ProductPatchChangesEnvelope:
    """Return a compact old/new diff for one persisted draft patch."""
    persisted_patch = patch_repository.get_patch_by_id(patch_id)
    if persisted_patch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Persisted patch '{patch_id}' was not found.",
        )

    changes: dict[str, list[object]] = {}
    for market_id, marketplace_summary in persisted_patch.diff_summary.get("marketplaces", {}).items():
        for field_change in marketplace_summary.get("field_changes", []):
            changes[f"{market_id}[{field_change['field']}]"] = [
                field_change.get("before", ""),
                field_change.get("after", ""),
            ]
        for feature_change in marketplace_summary.get("feature_changes", []):
            changes[f"{market_id}[feature:{feature_change['feature']}]"] = [
                feature_change.get("before", []),
                feature_change.get("after", []),
            ]

    return ProductPatchChangesEnvelope(
        data=ProductPatchChangesResponse(
            patch_id=patch_id,
            changes=changes,
        )
    )


@router.get("/{product_id}", response_model=ProductAggregateEnvelope)
def get_product_by_id(
    product_id: int,
    service: GetProductAggregateService = Depends(get_product_aggregate_service),
) -> ProductAggregateEnvelope:
    """Return the latest persisted aggregate for one internal product id."""
    aggregate = service.get_by_id(product_id=product_id)
    if aggregate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id '{product_id}' was not found.",
        )
    return ProductAggregateEnvelope(data=ProductAggregateResponse.from_domain(aggregate))
