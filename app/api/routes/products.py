from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_payload_service,
    get_preview_patch_service,
    get_product_aggregate_service,
    get_product_refresh_service,
    get_runtime_settings,
)
from app.api.schemas import (
    BuildPayloadRequest,
    BuildPayloadResponse,
    PersistedProductPatchEnvelope,
    PersistedProductPatchResponse,
    PreviewPatchRequest,
    ProductAggregateEnvelope,
    ProductAggregateResponse,
    RefreshProductRequest,
)
from app.application.services.product_aggregate import GetProductAggregateService, RefreshProductAggregateService
from app.application.services.product_payload import BuildSavePayloadService
from app.application.services.product_preview import PreviewProductPatchService
from app.infrastructure.settings import Settings

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/refresh", response_model=ProductAggregateEnvelope)
def refresh_product(
    request: RefreshProductRequest,
    service: RefreshProductAggregateService = Depends(get_product_refresh_service),
    settings: Settings = Depends(get_runtime_settings),
) -> ProductAggregateEnvelope:
    """Refresh one product from FOKS, persist a new snapshot, and return the latest aggregate."""
    base_url = request.base_url or settings.foks_base_url
    username = request.username or settings.foks_username
    password = request.password or settings.foks_password

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set FOKS_USERNAME and FOKS_PASSWORD in .env or pass them in the request body.",
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


@router.post("/save-payload", response_model=BuildPayloadResponse)
def build_save_payload(
    request: BuildPayloadRequest,
    service: BuildSavePayloadService = Depends(get_payload_service),
    settings: Settings = Depends(get_runtime_settings),
) -> BuildPayloadResponse:
    """Build a ready-to-send save payload for one product article."""
    base_url = request.base_url or settings.foks_base_url
    username = request.username or settings.foks_username
    password = request.password or settings.foks_password

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set FOKS_USERNAME and FOKS_PASSWORD in .env or pass them in the request body.",
        )

    result = service.build_save_payload(
        base_url=base_url,
        username=username,
        password=password,
        article=request.article,
        mids=request.mids,
    )

    if request.payload_only:
        return BuildPayloadResponse(data=result["payload"])

    return BuildPayloadResponse(data=result)


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
